"""Validate declarations before authentication or Terraform initialization."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "terraform-hcl-standard" / "scripts"))
from iac_identity import canonical_state_key

PROVIDERS = {
    "aws-cloud": "aws", "azure-cloud": "azure", "vultr-vps": "vultr",
    "gcp-cloud": "gcp", "ucloud": "ucloud", "akamai-cloud": "akamai",
}
STAGES = ("bootstrap", "account", "resources")
ENVIRONMENTS = {"sit": "sit", "uat": "uat", "prod": "prod", "shared": "prod"}
SHA = re.compile(r"[0-9a-f]{40}")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@+-]{0,126}")


class ContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def output(values):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            for key, value in values.items():
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, separators=(",", ":"))
                require("\n" not in str(value), "multiline workflow output rejected")
                stream.write(f"{key}={value}\n")


def contained(root, relative):
    root = Path(root).resolve()
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(), "relative declaration path required")
    require(".." not in Path(relative).parts, "parent traversal rejected")
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path.is_file(), f"missing or escaping declaration: {relative}")
    return path


def checkout_sha(root, expected=None):
    actual = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    require(SHA.fullmatch(actual), "checkout must resolve to a full SHA")
    if expected:
        require(actual == expected, "checkout SHA differs from prepared contract")
    # Tracked edits would change declarations/code without changing HEAD.
    changed = subprocess.check_output(["git", "-C", str(root), "diff", "HEAD", "--name-only"], text=True).strip()
    require(not changed, "tracked checkout edits rejected")
    return actual


def source_file(root, relative):
    path = contained(root, relative)
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", relative], capture_output=True)
    require(tracked.returncode == 0, "declaration must be tracked at the selected GitOps SHA")
    return path


def owner_match(address, owners):
    return any(address == owner or address.startswith(owner + ".") or address.startswith(owner + "[") for owner in owners)


def state_lock_key(target):
    # Serialize one namespace's stages, even if another manifest renames its ID.
    # Terraform's backend lock remains the authoritative per-state lock.
    key = canonical_state_key(environment=target["environment"], project=target["project"], provider=target["provider"], account=target["account"], namespace=target.get("namespace", target["workspace"]))
    return hashlib.sha256(key.encode()).hexdigest()


def validate_target(target, gitops_root):
    require(isinstance(target, dict), "target must be a mapping")
    for key in ("id", "environment", "project", "provider", "account", "workspace"):
        require(isinstance(target.get(key), str) and IDENTIFIER.fullmatch(target[key]), f"invalid target {key}")
    namespace = target.get("namespace", target.get("workspace"))
    require(namespace == target["workspace"], "namespace/workspace alias mismatch")
    lifecycle = target.get("lifecycle", {"status": "active", "persistent": False})
    require(isinstance(lifecycle, dict) and lifecycle.get("status") in {"active", "migration", "retired"}, "invalid target lifecycle")
    require(type(lifecycle.get("persistent")) is bool, "explicit lifecycle persistence required")
    require(target["provider"] in PROVIDERS, "unsupported provider; existing hosts use their own adapter")
    require(target["environment"] in ENVIRONMENTS, "unsupported environment")
    require(target["account"] not in {"default", "primary", "main"}, "concrete account required")
    require(set(target.get("stages", {})) == set(STAGES), "declare all three stages explicitly")
    require(isinstance(target.get("auth"), dict), "provider authentication declaration required")
    auth = target["auth"]
    require(auth.get("expected_identity"), "actual provider identity binding required")
    for stage in STAGES:
        spec = target["stages"][stage]
        require(isinstance(spec, dict), "stage must be a mapping")
        require(spec.get("mode") in {"verify", "terraform", "not_applicable", "unsupported"}, "invalid stage mode")
        if spec["mode"] in {"not_applicable", "unsupported"}:
            require(isinstance(spec.get("reason"), str) and spec["reason"].strip(), "non-execution stage needs reason")
        if spec["mode"] == "not_applicable":
            require(stage == "account" and target["provider"] in {"vultr-vps", "akamai-cloud"}, "not_applicable requires provider capability")
        if spec["mode"] == "verify":
            require(stage == "bootstrap" or spec.get("checks"), "verify account needs live prerequisite checks")
        if spec.get("manifest"):
            source_file(gitops_root, spec["manifest"])
        if spec["mode"] == "terraform":
            require(target["provider"] != "azure-cloud", "Azure renderer not implemented; declare unsupported")
            if stage != "resources":
                require(target["provider"] == "gcp-cloud" and stage == "bootstrap", "account state split/adapter not implemented; declare unsupported or verify")
            manifest = spec.get("manifest")
            source_file(gitops_root, manifest)
            require((manifest.startswith("resources/") or (lifecycle["status"] != "active" and manifest.startswith("iac/migrations/resources/"))) and f"/{target['environment']}/{PROVIDERS[target['provider']]}/" in manifest,
                    "manifest provider/environment mismatch")
            if manifest.startswith("iac/migrations/resources/"):
                provenance = target.get("provenance", {})
                require(SHA.fullmatch(provenance.get("commit", "")) and isinstance(provenance.get("path"), str) and provenance["path"], "archived target provenance required")
                require(not Path(provenance["path"]).is_absolute() and ".." not in Path(provenance["path"]).parts, "invalid archived provenance path")
            require(isinstance(spec.get("owners"), list) and spec["owners"], "explicit Terraform address ownership required")
            require(all(re.fullmatch(r"[\w.\[\]\"-]+", x) for x in spec["owners"]), "invalid resource address")
            require(isinstance(spec.get("protected", []), list), "protected addresses must be a list")
            canonical = canonical_state_key(environment=target["environment"], project=target["project"], provider=target["provider"], account=target["account"], namespace=namespace)
            state = spec.get("state", {})
            key = state.get("key")
            if stage == "bootstrap":
                require(key in {
                    f"platform-ops-toolkit/{target['environment']}/{target['account']}/gcp-oidc-bootstrap/terraform.tfstate",
                    f"platform-ops-toolkit/shared/{auth.get('expected_identity')}/gcp-oidc-bootstrap/terraform.tfstate",
                }, "bootstrap legacy key must be retained explicitly")
            else:
                require(key == canonical, "state key does not match declared identity")
            require(state.get("cli_workspace", "default") == "default", "legacy CLI workspace requires reviewed state migration")
            if stage == "resources" and target["provider"] == "akamai-cloud" and "namespace" in target:
                global_config = yaml.safe_load(source_file(gitops_root, manifest).read_text()).get("global", {})
                for field, expected in (("provider", target["provider"]), ("environment", target["environment"]), ("project", target["project"]), ("account", target["account"]), ("state_namespace", namespace), ("workspace", namespace)):
                    require(global_config.get(field) == expected, f"resource manifest identity mismatch: {field}")
            require(spec.get("ownership_reviewed") is True, "resource/stage/state ownership review is required")
            require(not spec.get("backend_migration") and not spec.get("adopt"), "maintenance must not run in ordinary lifecycle")
    if target.get("validation") is not None:
        from .validation import validate_candidate
        validate_candidate(target, gitops_root)
    return target



def load_targets(gitops_root, manifest, *, environment=None, provider=None, account=None, namespace=None, project=None, include_migrations=False):
    """Resolve reviewed refs at one checkout; never scan state/backend objects for targets."""
    source = source_file(gitops_root, manifest)
    document = yaml.safe_load(source.read_text())
    require(isinstance(document, dict) and document.get("apiVersion") == "gitops.svc.plus/v1alpha1", "IaC declaration required")
    migrations = []
    files = {manifest: digest(source)}
    if document.get("kind") == "IaCTargetCatalog":
        refs = document.get("target_manifests")
        require(isinstance(refs, list) and refs and all(isinstance(ref, str) for ref in refs) and len(refs) == len(set(refs)), "unique nonempty target references required")
        targets = []
        for ref in refs:
            path = source_file(gitops_root, ref)
            child = yaml.safe_load(path.read_text())
            require(isinstance(child, dict) and child.get("kind") == "IaCPipelineTargets" and child.get("apiVersion") == document["apiVersion"], "catalog references must be target manifests")
            require(isinstance(child.get("targets"), list) and child["targets"], "empty target reference")
            for target in child["targets"]:
                require("namespace" in target and "lifecycle" in target, "catalog targets require explicit namespace/lifecycle")
                targets.append(target)
            files[ref] = digest(path)
        migrations = document.get("migration_sources", [])
        require(isinstance(migrations, list), "migration_sources must be a list")
    else:
        require(document.get("kind") == "IaCPipelineTargets", "IaCPipelineTargets or IaCTargetCatalog required")
        targets = document.get("targets", [])
    require(isinstance(targets, list) and targets, "empty target set rejected")
    ids, keys = set(), set()
    for target in targets:
        validate_target(target, gitops_root)
        require(target["id"] not in ids, "duplicate target")
        ids.add(target["id"])
        for stage in target["stages"].values():
            if stage.get("mode") == "terraform":
                require(stage["state"]["key"] not in keys, "duplicate state ownership")
                keys.add(stage["state"]["key"])
    for item in migrations:
        require(isinstance(item, dict), "migration source must be a mapping")
        for field in ("id", "environment", "project", "provider", "account", "namespace"):
            require(isinstance(item.get(field), str) and IDENTIFIER.fullmatch(item[field]), f"invalid migration {field}")
        require(item["id"] not in ids, "duplicate migration identity")
        ids.add(item["id"])
        require(item.get("lifecycle", {}).get("status") == "migration" and item.get("read_only") is True, "historical state sources must be read-only migration objects")
        require(item["provider"] in PROVIDERS and item["environment"] in ENVIRONMENTS, "unsupported migration provider/environment")
        require(item["account"] not in {"primary", "default", "main"}, "concrete migration account required")
        require(type(item["lifecycle"].get("persistent")) is bool, "migration persistence required")
        provenance = item.get("provenance", {})
        require(SHA.fullmatch(provenance.get("commit", "")) and isinstance(provenance.get("path"), str) and provenance["path"], "historical source provenance required")
        require(not Path(provenance["path"]).is_absolute() and ".." not in Path(provenance["path"]).parts, "invalid historical source path")
        key = item.get("state", {}).get("key", "")
        prefix = f"terraform/{item['environment']}/{item['project']}/{item['provider']}/{item['account']}/"
        require(key == prefix + item["namespace"] + "/terraform.tfstate", "historical state key/identity mismatch")
        require(item.get("state", {}).get("cli_workspace") == "default", "migration workspace must be explicit")
        require(key not in keys, "migration state overlaps active target")
        keys.add(key)
    def selected(item):
        return all(value is None or (item.get("namespace", item.get("workspace")) if field == "workspace" else item.get(field)) == value for field, value in (("environment", environment), ("provider", provider), ("account", account), ("workspace", namespace), ("project", project)))
    chosen = [t for t in targets if selected(t) and (include_migrations or t.get("lifecycle", {}).get("status", "active") == "active")]
    require(chosen, "no matching declared IaC targets")
    return chosen, [m for m in migrations if selected(m)], files

def prepare(gitops_root, iac_root, manifest, environment, action, scope, bootstrap_mode, correlation, requested_refs, selectors=None):
    require(action in {"check", "plan", "apply", "destroy"}, "invalid action")
    require(scope in {"all", *STAGES}, "invalid stage scope")
    require(bootstrap_mode in {"verify", "reconcile"}, "invalid bootstrap mode")
    require(bootstrap_mode != "reconcile" or scope in {"all", "bootstrap"}, "reconcile needs explicit bootstrap scope")
    require(environment in ENVIRONMENTS, "invalid environment")
    iac_sha, gitops_sha = checkout_sha(iac_root), checkout_sha(gitops_root)
    source = source_file(gitops_root, manifest)
    selectors = selectors or {}
    require(set(selectors) <= {"environment", "provider", "account", "workspace", "namespace", "project"}, "unknown target selector")
    require(not selectors.get("environment") or selectors["environment"] == environment, "selector environment mismatch")
    require(not selectors.get("namespace") or not selectors.get("workspace") or selectors["namespace"] == selectors["workspace"], "selector namespace/workspace mismatch")
    targets, _, declaration_files = load_targets(gitops_root, manifest, environment=environment,
        provider=selectors.get("provider") or None, account=selectors.get("account") or None,
        namespace=selectors.get("namespace") or selectors.get("workspace") or None,
        project=selectors.get("project") or None, include_migrations=action == "check")
    ids, keys = set(), set()
    selected = list(STAGES) if scope == "all" else [scope]
    if action == "destroy" and any(target.get("validation") for target in targets):
        require(len(targets) == 1 and scope == "resources", "validation cleanup is one target/resources only")
    if action == "destroy":
        selected.reverse()
    for target in targets:
        validate_target(target, gitops_root)
        require(action == "check" or ("namespace" in target and "lifecycle" in target), "execution requires explicit namespace/lifecycle")
        require(action == "check" or target.get("lifecycle", {}).get("status", "active") == "active", "migration/retired targets are read-only")
        require(target["id"] not in ids, "duplicate target")
        require(target["environment"] == environment, "input must not override declared environment")
        ids.add(target["id"])
        for stage, spec in target["stages"].items():
            if spec.get("manifest"):
                spec["manifest_sha256"] = digest(source_file(gitops_root, spec["manifest"]))
            if spec["mode"] == "terraform":
                require(spec["state"]["key"] not in keys, "one state cannot be owned by multiple targets/stages")
                keys.add(spec["state"]["key"])
            if action != "check" and stage in selected:
                require(spec["mode"] != "unsupported", f"{target['id']}/{stage}: {spec.get('reason')}")
                if stage == "bootstrap" and bootstrap_mode == "reconcile":
                    require(spec["mode"] == "terraform", "reconcile requires an implemented bootstrap state owner; API-key verification is not reconciliation")
                if action == "destroy":
                    require(spec["mode"] != "verify", "shared/external prerequisites cannot be destroyed")
                    require(not target.get("lifecycle", {}).get("persistent", False), "persistent lifecycle blocks destruction")
                    require(spec.get("destroy_allowed") is True or spec["mode"] == "not_applicable", "destroy is not authorized by declaration")
                    require(not spec.get("shared") and not spec.get("external_references"), "shared/external references block destruction")
                    require(not spec.get("management_identity") and not spec.get("backend"), "execution identity/backend require independent retirement")
                    require(not (target["provider"] == "gcp-cloud" and (environment == "shared" or target["workspace"] == "web-saas")), "GCP shared/web-saas destroy remains protected")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    approval_environments = {"production" if environment == "prod" and t["provider"] == "aws-cloud" else ENVIRONMENTS[environment] for t in targets}
    context = {
        "schema_version": 1, "action": action, "stage_scope": scope, "stages": selected,
        "environment": environment, "github_environment": next(iter(approval_environments)) if len(approval_environments) == 1 else "",
        "bootstrap_mode": bootstrap_mode, "correlation_id": correlation or f"{run_id}:{attempt}",
        "run_id": run_id, "run_attempt": attempt,
        "workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF", "local"),
        "workflow_sha": os.environ.get("GITHUB_WORKFLOW_SHA", "local"),
        "gitops_sha": gitops_sha, "iac_sha": iac_sha, "requested_refs": requested_refs,
        "manifest_path": manifest, "manifest_sha256": digest(source), "selectors": selectors, "declaration_files": declaration_files, "targets": targets,
    }
    context["contract_sha256"] = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    return context


def revalidate(context, gitops_root, iac_root):
    checkout_sha(iac_root, context["iac_sha"])
    checkout_sha(gitops_root, context["gitops_sha"])
    source = source_file(gitops_root, context["manifest_path"])
    require(digest(source) == context["manifest_sha256"], "manifest digest mismatch")
    original = json.loads(json.dumps(context))
    expected = original.pop("contract_sha256")
    require(hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest() == expected, "contract digest mismatch")
    selectors = context.get("selectors", {})
    declaration, _, files = load_targets(gitops_root, context["manifest_path"], environment=context["environment"],
        provider=selectors.get("provider") or None, account=selectors.get("account") or None,
        namespace=selectors.get("namespace") or selectors.get("workspace") or None,
        project=selectors.get("project") or None, include_migrations=context["action"] == "check")
    require(files == context.get("declaration_files", files), "catalog target references changed")
    normalized = json.loads(json.dumps(declaration))
    for target in normalized:
        validate_target(target, gitops_root)
        for spec in target["stages"].values():
            if spec.get("manifest"):
                spec["manifest_sha256"] = digest(source_file(gitops_root, spec["manifest"]))
    require(normalized == context["targets"], "contract identity/config differs from GitOps declaration")
    return context
