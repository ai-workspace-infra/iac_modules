"""Saved-plan lifecycle, protected ownership and explicit dependency evidence."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from .auth import verify_checks, verify_identity
from .contracts import STAGES, ContractError, contained, digest, owner_match, read_json, require, revalidate, write_json
from .evidence import collect, guard_plan, receipt_base, sanitize_inventory


def run(command, private, allowed=(0,)):
    result = subprocess.run(command, capture_output=True)
    # Terraform output may contain sensitive values. Keep logs private, never upload.
    with open(Path(private) / "commands.log", "ab") as log:
        log.write(result.stdout + result.stderr)
    require(result.returncode in allowed, f"owner command failed: {Path(command[0]).name}; inspect private runner diagnostics")
    return result


def terraform(root, private, *args, allowed=(0,)):
    return run(["terraform", f"-chdir={root}", *args], private, allowed)


def render(context, target, stage, iac_root, gitops_root, private):
    spec = target["stages"][stage]
    source = contained(gitops_root, spec["manifest"])
    require(digest(source) == spec["manifest_sha256"], "stage manifest changed")
    source_tree = Path(iac_root) / "terraform-hcl-standard" / target["provider"]
    tree = Path(private) / "provider"
    # Existing renderers have fixed relative module paths: envs/<environment>/<namespace>.
    root = tree / "envs" / target["environment"] / target["workspace"]
    require(not root.exists(), "execution root already exists; reuse could select stale state/config")
    if stage == "bootstrap":
        require(target["provider"] == "gcp-cloud", "bootstrap reconciler not implemented")
        root = Path(private) / "identity"
        shutil.copytree(source_tree / "bootstrap" / "identity", root, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*", "*.tfvars*"))
        spec_doc = yaml.safe_load(source.read_text())["spec"]
        for key, expected in {"project_id": target["auth"]["expected_identity"], "gcp_account_id": target["account"]}.items():
            require(spec_doc.get(key) == expected, "bootstrap identity/manifest mismatch")
        require(spec_doc.get("repository") == "ai-workspace-infra/platform-ops-toolkit", "bootstrap repository mismatch")
        values = {
            "project_id": spec_doc["project_id"], "environment": target["environment"],
            "github_owner": "ai-workspace-infra", "github_repository": "platform-ops-toolkit",
            "pool_id": spec_doc["pool_id"], "provider_id": spec_doc["provider_id"],
            "audience": spec_doc["audience"], "deploy_service_account_id": spec_doc["service_account_id"],
            "allowed_subjects": spec_doc["subjects"],
        }
        write_json(root / "unified.auto.tfvars.json", values)
    else:
        shutil.copytree(source_tree, tree, ignore=shutil.ignore_patterns("envs", ".terraform", "*.tfstate*", "*.tfvars*", "__pycache__"))
        root.parent.mkdir(parents=True, exist_ok=True)
        args = [sys.executable, str(tree / "scripts" / "generate.py"), "render", "--resources", str(source), "--workdir", str(root)]
        if target["provider"] == "akamai-cloud":
            args += ["--namespace", target["workspace"]]
        for key, value in spec.get("render_env", {}).items():
            require(key in {"TARGET_DOMAIN_BASE", "TARGET_DOMAIN", "INSTANCE_PLAN_API", "AGENT_PROXY_PLAN_API", "TF_WORKSPACE_PREFIX"}, "unreviewed renderer environment override")
            os.environ[key] = str(value)
        run(args, private)
    return root, source


def initialize(root, private, state):
    require(state.get("cli_workspace", "default") == "default", "implicit workspace creation forbidden")
    # Provider and backend credentials are independent; never overwrite AWS OIDC keys.
    backend = {
        "bucket": os.environ["TF_STATE_BUCKET"], "key": state["key"],
        "region": os.environ["TF_STATE_REGION"], "access_key": os.environ["TF_STATE_ACCESS_KEY"],
        "secret_key": os.environ["TF_STATE_SECRET_KEY"],
        "endpoints": {"s3": os.environ["TF_STATE_ENDPOINT"]},
        "skip_credentials_validation": True, "skip_region_validation": True,
        "skip_requesting_account_id": True, "skip_metadata_api_check": True,
        "use_path_style": True, "use_lockfile": True,
    }
    path = Path(private) / "backend.hcl"
    path.write_text("\n".join(f"{k} = {json.dumps(v)}" for k, v in backend.items()) + "\n")
    os.chmod(path, 0o600)
    terraform(root, private, "init", "-input=false", f"-backend-config={path}")
    terraform(root, private, "fmt", "-no-color")
    terraform(root, private, "validate", "-no-color")


def dependencies(context, target, stage, dependencies_root):
    order = list(STAGES)
    if context["action"] == "destroy":
        order.reverse()
    before = order[:order.index(stage)]
    chosen_before = [s for s in before if s in context["stages"]]
    if chosen_before:
        receipts = collect(context, dependencies_root, chosen_before)
        for predecessor in chosen_before:
            receipt = receipts[(target["id"], predecessor)][1]
            if context["action"] == "destroy":
                require(receipt["result"] in {"destroyed_verified", "not_applicable"}, "downstream cleanup unproven")
    for predecessor in before:
        if predecessor in chosen_before:
            continue
        spec = target["stages"][predecessor]
        if context["action"] == "destroy":
            require(spec["mode"] == "not_applicable", "destroy of an upper layer requires explicit downstream cleanup receipts")
        elif spec["mode"] == "verify":
            if predecessor == "bootstrap":
                verify_identity(target)
            else:
                verify_checks(target, spec["checks"])
        elif spec["mode"] == "not_applicable":
            pass
        else:
            raise ContractError("blocked_by_unprovisioned_dependency: include prerequisite stage; saved external receipts are not silently reused")


def execute(context, target_id, stage, iac_root, gitops_root, evidence, private, dependencies_root):
    revalidate(context, gitops_root, iac_root)
    target = next(t for t in context["targets"] if t["id"] == target_id)
    require(stage in context["stages"], "stage was not selected by master")
    spec = target["stages"][stage]
    receipt = receipt_base(context, target, stage)
    receipt["verification"]["contract"] = True
    evidence, private = Path(evidence), Path(private)
    evidence.mkdir(parents=True, exist_ok=True)
    private.mkdir(parents=True, exist_ok=True)
    os.chmod(private, 0o700)
    write_json(evidence / "receipt.json", receipt)
    try:
        if spec["mode"] == "not_applicable":
            dependencies(context, target, stage, dependencies_root)
            receipt.update(result="not_applicable", reason=spec["reason"])
        else:
            verify_identity(target, runtime=not (stage == "bootstrap" and context["bootstrap_mode"] == "reconcile"))
            receipt["verification"]["identity"] = True
            dependencies(context, target, stage, dependencies_root)
            receipt["verification"]["dependencies"] = True
            if spec["mode"] == "verify" or (stage == "bootstrap" and context["bootstrap_mode"] == "verify"):
                require(context["action"] != "destroy", "verification identity/network is protected from destroy")
                if stage != "bootstrap":
                    verify_checks(target, spec["checks"])
                receipt["result"] = "verified_existing"
                receipt["verification"]["runtime_identity"] = True
            else:
                require(spec["mode"] == "terraform", "unsupported stage")
                root, source = render(context, target, stage, iac_root, gitops_root, private)
                write_json(private / "root.json", {"root": str(root), "stage": stage})
                initialize(root, private, spec["state"])
                if spec.get("requires_existing_state"):
                    current = terraform(root, private, "state", "list").stdout.decode().splitlines()
                    require(current and all(owner_match(address, spec["owners"]) for address in current), "existing state missing or belongs to another stage; explicit maintenance required")
                plan = private / "reviewed.tfplan"
                args = ["plan", "-input=false", "-lock-timeout=5m", f"-out={plan}", "-no-color"]
                if context["action"] == "destroy":
                    before = terraform(root, private, "state", "list").stdout.decode().splitlines()
                    require(before, "empty state destroy requires target investigation; refusing false success")
                    require(all(owner_match(address, spec["owners"]) for address in before), "state contains resources outside selected owner")
                    args.append("-destroy")
                terraform(root, private, *args)
                plan_doc = json.loads(terraform(root, private, "show", "-json", str(plan)).stdout)
                receipt["changes"] = guard_plan(target, stage, plan_doc, context["action"])
                receipt["plan_sha256"] = digest(plan)
                receipt["verification"]["ownership"] = True
                receipt["result"] = "planned"
                if context["action"] in {"apply", "destroy"}:
                    require(digest(plan) == receipt["plan_sha256"], "saved plan changed before apply")
                    terraform(root, private, "apply", "-input=false", "-lock-timeout=5m", str(plan))
                    args = ["plan", "-input=false", "-lock-timeout=5m", "-detailed-exitcode", "-no-color"]
                    if context["action"] == "destroy":
                        args.append("-destroy")
                        require(not terraform(root, private, "state", "list").stdout.strip(), "resources remain in target state")
                    terraform(root, private, *args)  # Exit 2 is drift, not verified success.
                    receipt["verification"]["convergence"] = True
                    receipt["result"] = "applied_verified" if context["action"] == "apply" else "destroyed_verified"
                    if context["action"] == "apply" and stage == "resources":
                        tree = Path(iac_root) / "terraform-hcl-standard" / target["provider"]
                        run([sys.executable, str(tree / "scripts" / "generate.py"), "inventory", "--resources", str(source), "--workdir", str(root)], private)
                        raw = read_json(root / "cmdb.json")
                        if target["provider"] == "gcp-cloud":
                            raw = {k: v for k, v in raw.items() if isinstance(v, dict) and ("instance_id" in v or "ip" in v)}
                        inventory = sanitize_inventory(raw)
                        require(inventory or target["provider"] == "gcp-cloud", "empty host inventory")
                        write_json(evidence / "inventory.json", inventory)
                        receipt["inventory_sha256"] = digest(evidence / "inventory.json")
    except Exception:
        receipt["result"] = "failed"
        raise
    finally:
        write_json(evidence / "receipt.json", receipt)
    return receipt


def cleanup(private):
    private = Path(private)
    try:
        if (private / "vault-token").is_file():
            token = (private / "vault-token").read_text()
            session = read_json(private / "vault-session.json")
            require(0 < session["lease_duration"] <= 1200, "unbounded Vault token cleanup")
            import urllib.request
            # Batch tokens are non-revocable. Their role TTL bounds them; remove
            # every local copy without falsely claiming server-side revocation.
            if session["token_type"] != "batch":
                req = urllib.request.Request("https://vault.svc.plus/v1/auth/token/revoke-self", headers={"X-Vault-Token": token}, data=b"{}")
                with urllib.request.urlopen(req, timeout=30) as response:
                    require(response.status == 204, "Vault session cleanup not verified")
    finally:
        if (private / "root.json").is_file():
            root = Path(read_json(private / "root.json")["root"])
            if read_json(private / "root.json")["stage"] == "bootstrap":
                (root / "unified.auto.tfvars.json").unlink(missing_ok=True)
                shutil.rmtree(root / ".terraform", ignore_errors=True)
            else:
                shutil.rmtree(root)
        if private.exists():
            shutil.rmtree(private)
        if os.environ.get("GITHUB_WORKSPACE"):
            for path in Path(os.environ["GITHUB_WORKSPACE"]).glob("gha-creds-*.json"):
                path.unlink(missing_ok=True)
        if os.environ.get("GITHUB_ENV"):
            keys = [k for k in os.environ if k.startswith(("TF_STATE_", "TF_VAR_", "AWS_", "GCP_BOOTSTRAP_", "UCLOUD_")) or k in {"GOOGLE_OAUTH_ACCESS_TOKEN", "CLOUDSDK_AUTH_ACCESS_TOKEN", "CLOUDSDK_CONFIG", "AZURE_CONFIG_DIR", "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_GHA_CREDS_PATH", "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE", "VULTR_API_KEY", "LINODE_TOKEN"}]
            with open(os.environ["GITHUB_ENV"], "a") as stream:
                for key in keys:
                    stream.write(key + "=\n")
