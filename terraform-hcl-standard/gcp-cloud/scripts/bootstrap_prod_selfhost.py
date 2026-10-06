#!/usr/bin/env python3
"""One-time, bounded repair of the existing PROD IAM/API and policy states.

This owner never creates a VM, network, disk, DB or application. Credentials
are environment-only; raw Terraform output/plans live in a private temporary
workspace that is removed on success or failure. Only a sanitized receipt is
printed. The controller must pin both source commits.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
PROJECT = "open-platform-prod"
PROJECT_NUMBER = "986070475391"
MEMBER = f"serviceAccount:github-actions-prod@{PROJECT}.iam.gserviceaccount.com"
INSTANCE = f"projects/{PROJECT}/zones/asia-east1-a/instances/web-saas-prod"
POLICY = "google_org_policy_policy.vm_external_ip_access"
IDENTITY_KEY = "platform-ops-toolkit/prod/xworktech/gcp-oidc-bootstrap/terraform.tfstate"
RESOURCE_KEY = "terraform/prod/svc.plus/gcp-cloud/xworktech/web-saas/terraform.tfstate"
OIDC_PATH = "resources/xworktech.com/prod/gcp/github-actions-oidc.yaml"
RESOURCE_PATH = "resources/svc.plus/prod/gcp/web-saas.yaml"
ROLES = ("roles/compute.securityAdmin", "roles/orgpolicy.policyViewer")
TARGETS = {
    "identity": [*(f'google_project_iam_member.deploy["{role}"]' for role in ROLES),
                 'google_project_service.platform["orgpolicy.googleapis.com"]'],
    "external-ip": [POLICY],
}
STATE_ENV = ("TF_STATE_ENDPOINT", "TF_STATE_BUCKET", "TF_STATE_ACCESS_KEY",
             "TF_STATE_SECRET_KEY", "TF_STATE_REGION")


class BootstrapError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise BootstrapError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_checkout(path, ref, repository):
    require(re.fullmatch(r"[0-9a-f]{40}", ref) is not None, "source refs must be full commit SHAs")
    try:
        head = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
        remote = subprocess.check_output(["git", "-C", str(path), "remote", "get-url", "origin"], text=True).strip()
        changes = subprocess.check_output(["git", "-C", str(path), "status", "--porcelain", "--untracked-files=all"], text=True)
    except subprocess.CalledProcessError as exc:
        raise BootstrapError("cannot verify source checkout") from exc
    require(head == ref, "source checkout differs from its fixed commit")
    require(remote in (f"https://github.com/{repository}.git", f"https://github.com/{repository}",
                       f"git@github.com:{repository}.git"), "unexpected source repository")
    require(not changes, "source checkout must be clean")


def declarations(gitops):
    oidc = yaml.safe_load((gitops / OIDC_PATH).read_text())
    resource = yaml.safe_load((gitops / RESOURCE_PATH).read_text())
    require(oidc.get("kind") == "GitHubActionsOIDCConfig", "unexpected OIDC declaration kind")
    require(resource.get("kind") == "GCPWorkloadNamespace", "unexpected resource declaration kind")
    for item in (oidc, resource):
        require(item.get("apiVersion") == "gitops.svc.plus/v1alpha1", "unexpected declaration API")
        require(item.get("metadata", {}).get("environment") == "prod", "PROD declarations only")
        require(item.get("metadata", {}).get("provider") == "gcp", "GCP declarations only")
        require(item["spec"].get("project_id") == PROJECT, "project must be open-platform-prod")
        require(str(item["spec"].get("organization_id")) == "744119519286", "organization mismatch")
        require(item["spec"].get("gcp_account_id") == "xworktech", "account mismatch")
    spec = oidc["spec"]
    require(spec.get("repository") == "ai-workspace-infra/platform-ops-toolkit", "caller mismatch")
    require(spec.get("service_account_id") == "github-actions-prod", "runtime identity mismatch")
    require(spec.get("pool_id") == "github-actions" and spec.get("provider_id") == "github", "WIF identity mismatch")
    audience = f"https://iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-actions/providers/github"
    require(spec.get("audience") == audience, "WIF audience mismatch")
    require(spec.get("provider_url") == "https://token.actions.githubusercontent.com", "OIDC issuer mismatch")
    subjects = ["repo:ai-workspace-infra/platform-ops-toolkit:environment:prod",
                "repo:ai-workspace-infra/platform-ops-toolkit:ref:refs/heads/main",
                "repo:ai-workspace-infra/platform-ops-toolkit:ref:refs/tags/v*",
                "repo:ai-workspace-infra/platform-ops-toolkit:ref:refs/tags/uat-*"]
    require(sorted(spec.get("subjects", [])) == sorted(subjects), "WIF subjects differ from existing contract")
    require(spec.get("state", {}).get("key") == IDENTITY_KEY, "identity state key mismatch")
    rs = resource["spec"]
    require(rs.get("state", {}).get("key") == RESOURCE_KEY, "resource state key mismatch")
    require(resource.get("metadata", {}).get("name") == "web-saas", "resource name mismatch")
    require(rs.get("workspace") == "web-saas" and rs.get("state_namespace") == "web-saas"
            and rs.get("state_project") == "svc.plus", "resource namespace mismatch")
    require(rs.get("manage_external_ip_policy", True) is True, "existing namespace must own policy")
    require(rs.get("external_ip_allowed_instances") == [{"name": "web-saas-prod", "zone": "asia-east1-a"}],
            "external IP allowlist must contain only web-saas-prod")
    return oidc, resource


def inspect_plan(plan, stage):
    # Targeted repair is intentionally a partial stack plan. Deferred target
    # changes or an errored plan are still unsupported.
    require(plan.get("errored") is not True and not plan.get("deferred_changes"),
            "Terraform plan is errored or has deferred changes")
    changes = plan.get("resource_changes")
    require(isinstance(changes, list), "Terraform plan resource changes are missing")
    seen = set()
    receipt = []
    for item in changes:
        address = item.get("address")
        change = item.get("change", {})
        actions = change.get("actions")
        require(actions in (["no-op"], ["read"], ["create"], ["update"]), "delete/replace/unknown action rejected")
        if item.get("mode") == "data":
            require(stage == "external-ip" and address == "module.project.data.google_project.existing[0]",
                    "unexpected data dependency")
            continue
        if actions == ["no-op"] and address not in TARGETS[stage]:
            continue
        require(address in TARGETS[stage], "plan writes outside bootstrap targets")
        require(address not in seen, "duplicate target resource")
        seen.add(address)
        after = change.get("after") or {}
        require(not any(change.get("after_unknown", {}).get(key) is True for key in ("project", "role", "member", "parent", "spec")),
                "target contract contains unknown values")
        if stage == "identity":
            require(after.get("project") == PROJECT, "IAM/API project mismatch")
            if item.get("type") == "google_project_iam_member":
                require(after.get("role") in ROLES and after.get("member") == MEMBER, "IAM grant mismatch")
                require(address == f'google_project_iam_member.deploy["{after["role"]}"]', "IAM address mismatch")
                require(not after.get("condition"), "conditional IAM contract is unsupported")
            else:
                require(item.get("type") == "google_project_service" and after.get("service") == "orgpolicy.googleapis.com",
                        "API enablement mismatch")
                require(after.get("disable_on_destroy") is False, "API must survive teardown")
        else:
            require(item.get("type") == "google_org_policy_policy", "policy resource type mismatch")
            require(after.get("name") in (f"projects/{PROJECT_NUMBER}/policies/compute.vmExternalIpAccess", "compute.vmExternalIpAccess"),
                    "policy constraint identity mismatch")
            require(after.get("parent") == f"projects/{PROJECT}", "policy parent mismatch")
            specs = after.get("spec", [])
            require(len(specs) == 1 and not specs[0].get("inherit_from_parent") and not specs[0].get("reset"),
                    "policy must use exact local rules")
            rules = specs[0].get("rules", [])
            require(len(rules) == 1 and not rules[0].get("condition") and rules[0].get("allow_all") in (None, "FALSE", False)
                    and rules[0].get("deny_all") in (None, "FALSE", False), "broad or conditional policy rejected")
            values = rules[0].get("values", [])
            require(len(values) == 1 and values[0].get("allowed_values") == [INSTANCE] and not values[0].get("denied_values"),
                    "policy must allow exactly the declared instance")
            before = change.get("before") or {}
            for old_spec in before.get("spec", []):
                for old_rule in old_spec.get("rules", []):
                    require(not old_rule.get("condition") and old_rule.get("allow_all") in (None, "FALSE", False),
                            "existing broad/conditional policy requires separate review")
                    for values in old_rule.get("values", []):
                        require(set(values.get("allowed_values", [])) <= {INSTANCE}, "existing policy allowances would be removed")
        contract = {key: after[key] for key in ("project", "role", "member", "service", "parent") if key in after}
        if stage == "external-ip":
            contract["allowed_instances"] = [INSTANCE]
        receipt.append({"address": address, "actions": actions, "contract": contract, "change_sha256": digest(change)})
    require(seen == set(TARGETS[stage]), "plan omitted a bootstrap target")
    return sorted(receipt, key=lambda item: item["address"])


def state_snapshot(state, stage):
    require(isinstance(state.get("lineage"), str) and bool(state["lineage"]), "existing state lineage is required")
    require(type(state.get("serial")) is int, "invalid state serial")
    protected = {}
    for item in state.get("resources", []):
        if item.get("mode") != "managed":
            continue
        base = ".".join(filter(None, (item.get("module"), item["type"], item["name"])))
        if stage == "identity" and item["type"] in ("google_service_account", "google_iam_workload_identity_pool", "google_iam_workload_identity_pool_provider"):
            protected[base] = digest(item.get("instances", []))
        if stage == "external-ip" and item["type"] in ("google_compute_network", "google_compute_subnetwork", "google_compute_disk", "google_compute_instance"):
            protected[base] = digest(item.get("instances", []))
    if stage == "identity":
        required = {"google_service_account.github_actions", "google_iam_workload_identity_pool.github",
                    "google_iam_workload_identity_pool_provider.github"}
    else:
        required = {"module.network.google_compute_network.this", "module.network.google_compute_subnetwork.this",
                    "module.data_disk_web_saas_prod.google_compute_disk.this"}
    require(required <= protected.keys(), "existing identity/network/data-disk state is missing; do not create a second state")
    return {"lineage": state["lineage"], "serial": state["serial"], "protected": protected}


def runtime_environment():
    require(bool(os.environ.get("GCP_BOOTSTRAP_ACCESS_TOKEN")), "approved short-lived GCP_BOOTSTRAP_ACCESS_TOKEN is required")
    require(all(os.environ.get(key) for key in STATE_ENV), "complete Vault TF_STATE environment contract is required")
    endpoint = os.environ["TF_STATE_ENDPOINT"]
    require(re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?/?", endpoint) is not None, "state endpoint must be HTTPS without credentials or a query")
    require(re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", os.environ["TF_STATE_BUCKET"]) is not None, "invalid state bucket")
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("TF_VAR_", "TF_CLI_ARGS", "TF_LOG", "AWS_", "GOOGLE_", "GCLOUD_"))
           and key not in ("TF_WORKSPACE", "TF_DATA_DIR", "GCP_BOOTSTRAP_ACCESS_TOKEN")}
    env.update(GOOGLE_OAUTH_ACCESS_TOKEN=os.environ["GCP_BOOTSTRAP_ACCESS_TOKEN"],
               AWS_ACCESS_KEY_ID=os.environ["TF_STATE_ACCESS_KEY"], AWS_SECRET_ACCESS_KEY=os.environ["TF_STATE_SECRET_KEY"],
               AWS_EC2_METADATA_DISABLED="true", TF_IN_AUTOMATION="1", TF_INPUT="0")
    return env


def existing_policy(token):
    name = f"projects/{PROJECT_NUMBER}/policies/compute.vmExternalIpAccess"
    request = urllib.request.Request(f"https://orgpolicy.googleapis.com/v2/{name}", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
        require(data.get("name") == name, "unexpected external policy identity")
        return name
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise BootstrapError(f"policy read failed (HTTP {exc.code}); complete IAM/API bootstrap first") from exc
    except urllib.error.URLError as exc:
        raise BootstrapError("policy read failed; no resources were assumed absent") from exc


class Terraform:
    def __init__(self, workdir, env):
        self.workdir, self.env = workdir, env

    def run(self, *args):
        result = subprocess.run(["terraform", f"-chdir={self.workdir}", *args], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # Raw provider diagnostics can include secrets. Never echo them.
        require(result.returncode == 0, f"Terraform {args[0]} failed; raw provider output withheld")
        return result.stdout


def execute(args):
    gitops = args.gitops_dir.resolve()
    verify_checkout(REPO, args.iac_ref, "ai-workspace-infra/iac_modules")
    verify_checkout(gitops, args.gitops_ref, "ai-workspace-infra/gitops")
    oidc, resource = declarations(gitops)
    env = runtime_environment()
    state_contract = (oidc if args.stage == "identity" else resource)["spec"]["state"]
    for key, field in (("TF_STATE_ENDPOINT", "endpoint"), ("TF_STATE_BUCKET", "bucket"), ("TF_STATE_REGION", "region")):
        require(os.environ[key] == state_contract.get(field), "Vault backend differs from the fixed GitOps state contract")
    os.umask(0o077)
    envs = ROOT / "envs"
    with tempfile.TemporaryDirectory(prefix=".prod-selfhost-bootstrap-", dir=envs) as temp:
        workdir = Path(temp)
        if args.stage == "identity":
            shutil.copyfile(ROOT / "bootstrap" / "identity" / "main.tf", workdir / "main.tf")
            spec = oidc["spec"]
            variables = {"project_id": PROJECT, "environment": "prod", "github_owner": "ai-workspace-infra",
                         "github_repository": "platform-ops-toolkit", "pool_id": spec["pool_id"],
                         "provider_id": spec["provider_id"], "audience": spec["audience"],
                         "deploy_service_account_id": spec["service_account_id"], "allowed_subjects": spec["subjects"]}
            (workdir / "terraform.auto.tfvars.json").write_text(json.dumps(variables))
            state_key = IDENTITY_KEY
        else:
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate.py"), "render",
                                     "--resources", str(gitops / RESOURCE_PATH), "--workdir", str(workdir)],
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            require(result.returncode == 0, "resource rendering failed")
            variables = json.loads((workdir / "terraform.auto.tfvars.json").read_text())
            variables.update(deploy_service_account=MEMBER.split(":", 1)[1],
                             workload_identity_provider=oidc["spec"]["audience"].removeprefix("https://iam.googleapis.com/"))
            (workdir / "terraform.auto.tfvars.json").write_text(json.dumps(variables))
            state_key = RESOURCE_KEY
        tf = Terraform(workdir, env)
        tf.run("init", "-input=false", "-reconfigure", "-no-color",
               f'-backend-config=endpoint={os.environ["TF_STATE_ENDPOINT"]}',
               f'-backend-config=bucket={os.environ["TF_STATE_BUCKET"]}', f"-backend-config=key={state_key}",
               f'-backend-config=region={os.environ["TF_STATE_REGION"]}',
               "-backend-config=skip_credentials_validation=true", "-backend-config=skip_metadata_api_check=true",
               "-backend-config=skip_region_validation=true", "-backend-config=use_path_style=true", "-backend-config=use_lockfile=true")
        tf.run("fmt", "-check", "-no-color")
        tf.run("validate", "-no-color")
        raw_state = json.loads(tf.run("state", "pull"))
        before = state_snapshot(raw_state, args.stage)
        if args.stage == "external-ip":
            policy_id = existing_policy(env["GOOGLE_OAUTH_ACCESS_TOKEN"])
            managed = any(item.get("type") == "google_org_policy_policy" and item.get("name") == "vm_external_ip_access"
                          and not item.get("module") for item in raw_state["resources"])
            if policy_id and not managed:
                # A reviewed import block adopts the existing object in the SAME
                # state, atomically with its saved plan. Plan does not import it.
                (workdir / "adopt_policy.tf").write_text(f'import {{\n  to = {POLICY}\n  id = "{policy_id}"\n}}\n')
        targets = [f"-target={address}" for address in TARGETS[args.stage]]
        planfile = workdir / "bootstrap.tfplan"
        tf.run("plan", "-input=false", "-no-color", "-lock-timeout=120s", f"-out={planfile}", *targets)
        plan = json.loads(tf.run("show", "-json", str(planfile)))
        changes = inspect_plan(plan, args.stage)
        versions = json.loads(tf.run("version", "-json"))
        provider_version = versions.get("provider_selections", {}).get("registry.terraform.io/hashicorp/google")
        require(bool(provider_version), "Google provider version must be recorded")
        receipt = {"schema": 1, "owner": "iac_modules", "scope": "prod-selfhost-bootstrap-only",
                   "stage": args.stage, "project": PROJECT, "iac_ref": args.iac_ref, "gitops_ref": args.gitops_ref,
                   "terraform_version": versions["terraform_version"], "google_provider_version": provider_version,
                   "backend": {"endpoint": os.environ["TF_STATE_ENDPOINT"], "bucket": os.environ["TF_STATE_BUCKET"]},
                   "state_key": state_key, "state_before": before, "targets": changes}
        plan_digest = digest(receipt)
        if args.action == "apply":
            require(args.approved_plan_sha256 == plan_digest, "fresh plan differs from the administrator-reviewed plan digest")
            tf.run("apply", "-input=false", "-no-color", "-lock-timeout=120s", str(planfile))
            after = state_snapshot(json.loads(tf.run("state", "pull")), args.stage)
            require(before["lineage"] == after["lineage"] and before["protected"] == after["protected"],
                    "protected resource state changed; stop before resource deployment")
            # Saved apply is not sufficient evidence of convergence.
            tf.run("plan", "-input=false", "-no-color", "-lock-timeout=120s", f"-out={planfile}", *targets)
            verify = inspect_plan(json.loads(tf.run("show", "-json", str(planfile))), args.stage)
            require(all(item["actions"] == ["no-op"] for item in verify), "bootstrap has not converged")
            receipt["state_after"] = after
        receipt.update(action=args.action, result="converged" if args.action == "apply" else "review-required",
                       approved_plan_sha256=plan_digest, database_cutover_approved=False)
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gitops-dir", required=True, type=Path)
    parser.add_argument("--gitops-ref", required=True)
    parser.add_argument("--iac-ref", required=True)
    parser.add_argument("--stage", choices=TARGETS, required=True)
    parser.add_argument("--action", choices=("plan", "apply"), default="plan")
    parser.add_argument("--approved-plan-sha256")
    args = parser.parse_args()
    try:
        require(args.action != "apply" or re.fullmatch(r"[0-9a-f]{64}", args.approved_plan_sha256 or ""),
                "apply requires a reviewed plan digest")
        print(json.dumps(execute(args), indent=2, sort_keys=True))
    except (BootstrapError, ValueError, KeyError, OSError) as exc:
        # Do not print arbitrary exception strings from provider/parser input.
        message = str(exc) if isinstance(exc, BootstrapError) else "invalid input or incomplete bootstrap execution"
        print(f"bootstrap stopped: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
