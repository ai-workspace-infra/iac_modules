#!/usr/bin/env python3
"""Action entry point. Environment inputs avoid shell interpolation of declarations."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from unified.auth import load_credentials, request_json, verify_identity
from unified.contracts import PROVIDERS, STAGES, ContractError, checkout_sha, contained, digest, output, prepare, read_json, require, state_lock_key, revalidate, source_file, validate_target, write_json
from unified.evidence import receipt_base, summarize, verify_summary
from unified.runtime import cleanup, execute


def env(key, default=None):
    if default is not None:
        return os.environ.get("IAC_" + key, default)
    return os.environ["IAC_" + key]


def context_target():
    context = read_json(env("CONTRACT"))
    revalidate(context, env("GITOPS_ROOT"), env("ROOT"))
    target = next((t for t in context["targets"] if t["id"] == env("TARGET")), None)
    require(target is not None, "target was not selected")
    require(env("STAGE") in context["stages"], "stage was not selected")
    return context, target


def main(command):
    if command == "prepare":
        context = prepare(env("GITOPS_ROOT"), env("ROOT"), env("MANIFEST"), env("ENVIRONMENT"), env("ACTION"),
                          env("SCOPE"), env("BOOTSTRAP_MODE", "verify"), env("CORRELATION", ""),
                          {"gitops": env("GITOPS_REF"), "iac": env("REF")})
        selectors = json.loads(env("SELECTORS", "{}"))
        for key, value in selectors.items():
            if value:
                require(all(t.get(key) == value for t in context["targets"]), f"legacy selector conflicts with declaration: {key}")
        write_json(env("CONTRACT"), context)
        outputs = {"gitops_sha": context["gitops_sha"], "iac_sha": context["iac_sha"], "contract_sha256": context["contract_sha256"],
                   "github_environment": context["github_environment"], "correlation_id": context["correlation_id"],
                   "targets": {"include": [{"target_id": t["id"], "provider": t["provider"], "lock_key": state_lock_key(t)} for t in context["targets"]]}}
        output(outputs)
    elif command == "resolve-caller":
        import yaml
        gitops = Path(env("GITOPS_ROOT"))
        selectors = json.loads(env("SELECTORS", "{}"))
        manifest = env("MANIFEST", "")
        if env("CALLER") == "serverless":
            topology = yaml.safe_load(source_file(gitops, env("TOPOLOGY")).read_text())
            declared = topology.get("spec", {}).get("iac", {}).get("target_manifest", "")
            require(not manifest or not declared or manifest == declared, "caller target conflicts with serverless topology")
            manifest = manifest or declared
            require(manifest, "serverless infrastructure target must be declared by GitOps")
        if not manifest:
            matches = []
            for path in (gitops / "iac" / "targets").glob("*.yaml"):
                declaration = yaml.safe_load(source_file(gitops, str(path.relative_to(gitops))).read_text())
                targets = declaration.get("targets", [])
                if len(targets) == 1 and all(not v or targets[0].get(k) == v for k, v in selectors.items()):
                    matches.append(str(path.relative_to(gitops)))
            require(len(matches) == 1, "no unique reviewed GitOps target; supply target_manifest instead of falling back to legacy state")
            manifest = matches[0]
        declaration = yaml.safe_load(source_file(gitops, manifest).read_text())
        require(declaration.get("kind") == "IaCPipelineTargets", "caller needs pipeline target declaration")
        for target in declaration["targets"]:
            require(all(not v or target.get(k) == v for k, v in selectors.items()), "caller selector disagrees with declared identity")
        state_key = env("STATE_KEY", "")
        if state_key:
            require(len(declaration["targets"]) == 1 and declaration["targets"][0]["stages"]["resources"].get("state", {}).get("key") == state_key, "caller state key differs from retained state")
        output({"target_manifest": manifest, "gitops_sha": checkout_sha(gitops), "iac_sha": checkout_sha(env("ROOT")), "selectors": selectors})
    elif command == "normalize-legacy":
        import yaml
        values = json.loads(env("INPUTS"))
        def alias(*keys, default=""):
            supplied = [str(values[k]) for k in keys if values.get(k) not in (None, "")]
            require(len(set(supplied)) <= 1, "conflicting aliases: " + "/".join(keys))
            return supplied[0] if supplied else default
        action = alias("action", "deploy_action", default="plan")
        environment = alias("environment", "vault_env_path")
        alias("iac_ref", "gcp_iac_ref")
        alias("gitops_ref", "gitops_repo_ref")
        provider = alias("cloud_provider", default=env("PROVIDER", ""))
        require(not env("PROVIDER", "") or provider == env("PROVIDER"), "provider wrapper selector conflict")
        require(action in {"check", "plan", "apply", "destroy"}, "invalid legacy action")
        require(not values.get("state_migration_source_key") and str(values.get("adopt_existing_platform_resources", "false")).lower() != "true", "adoption/migration requires explicit maintenance")
        require(not values.get("components_json") or json.loads(values["components_json"]) == [], "component selection must be moved to the reviewed target declaration")
        require(str(values.get("deploy_dry_run", "false")).lower() != "true" or action in {"plan", "check"}, "dry run cannot authorize apply/destroy")
        repo = values.get("gitops_repo_name", "")
        require(not repo or repo in {"ai-workspace-infra/gitops", "https://github.com/ai-workspace-infra/gitops.git"}, "legacy repository differs from the reviewed GitOps source")
        manifest = alias("target_manifest")
        resource = alias("resource_manifest", "gcp_resource_manifest", "gcp_oidc_manifest")
        if not resource and not manifest and env("STAGE") == "bootstrap" and provider == "gcp-cloud":
            resource = f"resources/xworktech.com/{environment}/gcp/github-actions-oidc.yaml"
        require(manifest or resource or values.get("workspace"), "legacy operations require an explicit manifest or workspace; broad provider defaults are no longer deploy targets")
        selectors = {"environment": environment}
        if provider:
            selectors["provider"] = provider
        account = alias("account", "state_account")
        if provider == "gcp-cloud":
            account = alias("account", "state_account", "gcp_account_id")
        for key, value in {"account": account, "project": values.get("project", ""), "workspace": values.get("workspace", "")}.items():
            if value:
                selectors[key] = value
        stage = env("STAGE")
        candidates = []
        for path in (Path(env("GITOPS_ROOT")) / "iac" / "targets").glob("*.yaml"):
            document = yaml.safe_load(source_file(env("GITOPS_ROOT"), str(path.relative_to(env("GITOPS_ROOT")))).read_text())
            targets = document.get("targets", [])
            if targets and all(target["stages"][stage]["mode"] != "unsupported" and all(not v or target.get(k) == v for k, v in selectors.items()) and (not resource or target["stages"][stage].get("manifest") == resource) for target in targets):
                candidates.append(str(path.relative_to(env("GITOPS_ROOT"))))
        if not manifest:
            require(len(candidates) == 1, "legacy selection needs a unique reviewed target_manifest")
            manifest = candidates[0]
        else:
            require(manifest in candidates, "new/legacy manifest or identity selectors conflict")
        declared = yaml.safe_load(source_file(env("GITOPS_ROOT"), manifest).read_text())["targets"]
        for target in declared:
            for legacy, field in (("aws_region", "region"), ("aws_role_arn", "role_arn")):
                if values.get(legacy):
                    require(target["provider"] == "aws-cloud" and values[legacy] == target["auth"].get(field), "legacy AWS auth override conflicts with GitOps")
            github_environment = "production" if environment == "prod" and target["provider"] == "aws-cloud" else ("prod" if environment == "shared" else environment)
            require(not values.get("github_environment") or values["github_environment"] == github_environment, "legacy approval environment conflicts with the controlled provider mapping")
        output({"target_manifest": manifest, "selectors": selectors, "action": action, "environment": environment,
                "gitops_sha": checkout_sha(env("GITOPS_ROOT")), "iac_sha": checkout_sha(env("ROOT"))})
    elif command == "caller-inventory":
        summary = read_json(env("SUMMARY"))
        require(summary["result"] == "applied_verified", "only verified apply inventory can feed host deployment")
        inventories = read_json(Path(env("SUMMARY")).parent / "inventory.json")
        cmdb = {}
        for inventory in inventories.values():
            for host, facts in inventory.items():
                require(host not in cmdb, "duplicate deployment host across targets")
                cmdb[host] = facts
        require(cmdb, "host deployment requires nonempty verified inventory")
        destination = Path(env("DESTINATION"))
        write_json(destination / "cmdb.json", cmdb)
        write_json(destination / "hosts_manifest.json", {"hosts": [dict(name=host, **{k: v for k, v in facts.items() if k != "name"}) for host, facts in cmdb.items()]})
        import shlex
        lines = []
        groups = {}
        for host, facts in cmdb.items():
            require(facts.get("ip"), "verified host is missing deployment IP")
            variables = {"ansible_host": facts["ip"], "ansible_user": facts.get("ansible_user", "root"), **facts.get("host_vars", {})}
            lines.append(host + " " + " ".join(k + "=" + shlex.quote(repr(v)) for k, v in variables.items()))
            for group in facts.get("groups", []):
                groups.setdefault(group, []).append(host)
        (destination / "inventory.ini").write_text("[all]\n" + "\n".join(lines) + "\n" + "".join(f"\n[{group}]\n" + "\n".join(hosts) + "\n" for group, hosts in groups.items()))
    elif command == "stage-context":
        context, target = context_target()
        require(context["contract_sha256"] == env("CHECKSUM"), "caller contract checksum mismatch")
        require(context["action"] == env("ACTION") and context["environment"] == env("ENVIRONMENT"), "caller operation/environment mismatch")
        require(context["iac_sha"] == env("SHA") and context["gitops_sha"] == env("GITOPS_SHA"), "caller immutable source mismatch")
        require(target["provider"] == env("PROVIDER") and state_lock_key(target) == env("LOCK_KEY"), "caller provider/state lock mismatch")
        require(context["run_id"] == os.environ["GITHUB_RUN_ID"] and context["run_attempt"] == os.environ["GITHUB_RUN_ATTEMPT"], "stale caller contract")
    elif command == "stage-prepare":
        context, target = context_target()
        stage = env("STAGE")
        spec = target["stages"][stage]
        require(context["action"] != "check", "check cannot authenticate/execute")
        require(spec["mode"] != "unsupported", "stage unsupported")
        write_json(Path(env("EVIDENCE")) / "receipt.json", receipt_base(context, target, stage))
        values = {"provider": target["provider"], "mode": spec["mode"], "reconcile": "true" if stage == "bootstrap" and context["bootstrap_mode"] == "reconcile" else "false"}
        output(values)
    elif command == "auth":
        context, target = context_target()
        load_credentials(context, target, env("STAGE"), env("PRIVATE"))
    elif command == "verify-identity":
        context, target = context_target()
        verify_identity(target)
    elif command == "execute":
        context, target = context_target()
        execute(context, target["id"], env("STAGE"), env("ROOT"), env("GITOPS_ROOT"), env("EVIDENCE"), env("PRIVATE"), env("DEPENDENCIES"))
    elif command == "verify-runtime":
        context, target = context_target()
        verify_identity(target)
        path = Path(env("EVIDENCE")) / "receipt.json"
        receipt = read_json(path)
        receipt["verification"]["runtime_identity"] = True
        write_json(path, receipt)
    elif command == "publish-runtime":
        context, target = context_target()
        if context["action"] != "apply" or context["bootstrap_mode"] != "reconcile":
            return
        require(target["provider"] == "gcp-cloud" and env("STAGE") == "bootstrap", "runtime metadata publisher is bootstrap-only")
        require(target["auth"]["record"] == f"kv/data/{target['environment']}/platform/oidc/{target['account']}", "runtime record publication must bind the selected account")
        private = Path(env("PRIVATE"))
        params = read_json(private / "auth.json")
        token = (private / "vault-token").read_text()
        payload = {"data": {"gcp_workload_identity_provider": params["provider"], "deploy_service_account": params["service_account"],
                            "gcp_oidc_audience": params["audience"], "project_id": target["auth"]["expected_identity"]}}
        request_json("https://vault.svc.plus/v1/" + target["auth"]["record"], {"X-Vault-Token": token, "Content-Type": "application/json"}, json.dumps(payload).encode())
        path = Path(env("EVIDENCE")) / "receipt.json"
        receipt = read_json(path)
        receipt["verification"]["runtime_metadata_published"] = True
        write_json(path, receipt)
    elif command == "bootstrap-cleanup":
        context, target = context_target()
        if env("STAGE") != "bootstrap" or context["bootstrap_mode"] != "reconcile" or context["action"] != "apply":
            return
        require(target["provider"] == "gcp-cloud", "bootstrap cleanup adapter missing")
        private = Path(env("PRIVATE"))
        require((private / "bootstrap-credential.json").is_file(), "bootstrap cleanup credential evidence missing")
        credential = read_json(private / "bootstrap-credential.json")
        import urllib.request
        def call(url, data, headers, method):
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(request, timeout=30) as response:
                require(response.status in {200, 204}, "bootstrap cleanup API failed")
        if credential.get("GCP_AUTH_JSON"):
            value = credential["GCP_AUTH_JSON"]
            key = json.loads(value) if isinstance(value, str) else value
            account = key["client_email"]
            require(account != target["auth"]["service_account"], "bootstrap credential must differ from runtime principal")
            headers = {"Authorization": "Bearer " + os.environ["GCP_BOOTSTRAP_ACCESS_TOKEN"], "Content-Type": "application/json"}
            call(f"https://iam.googleapis.com/v1/projects/-/serviceAccounts/{account}/keys/{key['private_key_id']}", None, headers, "DELETE")
            call(f"https://iam.googleapis.com/v1/projects/-/serviceAccounts/{account}:disable", b"{}", headers, "POST")
        token = (private / "vault-token").read_text()
        record = target["auth"]["bootstrap_record"]
        call("https://vault.svc.plus/v1/" + record.replace("kv/data/", "kv/metadata/", 1), None, {"X-Vault-Token": token}, "DELETE")
        path = Path(env("EVIDENCE")) / "receipt.json"
        receipt = read_json(path)
        receipt["verification"]["bootstrap_credential_removed"] = True
        write_json(path, receipt)
    elif command == "cleanup":
        path = Path(env("EVIDENCE")) / "receipt.json"
        receipt = read_json(path) if path.is_file() else None
        try:
            cleanup(env("PRIVATE"))
            if receipt:
                receipt["verification"]["cleanup"] = True
        except Exception:
            if receipt:
                receipt["verification"]["cleanup"] = False
                receipt["result"] = "failed"
            raise
        finally:
            if receipt:
                write_json(path, receipt)
    elif command == "receipt":
        path = Path(env("EVIDENCE")) / "receipt.json"
        require(path.is_file(), "execution receipt missing")
        receipt = read_json(path)
        if env("EXECUTION_RESULT") != "success" or env("CLEANUP_RESULT") != "success":
            receipt["result"] = "failed"
        write_json(path, receipt)
        output({"result": receipt["result"], "receipt_sha256": digest(path)})
        require(receipt["result"] != "failed", "stage execution/cleanup failed")
    elif command == "self-check":
        root, gitops = Path(env("ROOT")), Path(env("GITOPS_ROOT"))
        checkout_sha(root)
        checkout_sha(gitops)
        import yaml
        registry_path = source_file(gitops, "iac/capabilities.yaml")
        registry = yaml.safe_load(registry_path.read_text())
        require(registry.get("kind") == "IaCCapabilityDeclarations" and set(registry.get("providers", {})) == set(PROVIDERS), "six-provider GitOps capability declaration required")
        target_counts = {p: 0 for p in PROVIDERS}
        for path in (gitops / "iac" / "targets").glob("*.yaml"):
            declaration = yaml.safe_load(source_file(gitops, str(path.relative_to(gitops))).read_text())
            require(declaration.get("kind") == "IaCPipelineTargets" and declaration.get("targets"), "invalid static target declaration")
            for target in declaration["targets"]:
                validate_target(target, gitops)
                target_counts[target["provider"]] += 1
        reports = []
        selected = env("PROVIDERS", ",".join(PROVIDERS)).split(",")
        require(selected and len(set(selected)) == len(selected) and all(p in PROVIDERS for p in selected), "invalid static provider set")
        for provider in selected:
            tree = root / "terraform-hcl-standard" / provider
            require(tree.is_dir() and any(tree.rglob("*.tf")), f"missing module tree: {provider}")
            manifests = list((gitops / "resources").glob(f"*/*/{PROVIDERS[provider]}/*.yaml"))
            capability = registry["providers"][provider]
            require(all(capability.get(k) for k in (*STAGES, "reason")), "incomplete provider capability declaration")
            require(manifests or capability["resources"] == "unsupported", "missing provider GitOps resources without explicit unsupported capability")
            templates = 0
            for manifest in manifests:
                text = source_file(gitops, str(manifest.relative_to(gitops))).read_text()
                if "{{" in text or "{%" in text:
                    # Parse renderer templates without populating environment
                    # values or pretending that this is runtime configuration.
                    from jinja2 import Environment
                    Environment().parse(text)
                    templates += 1
                else:
                    require(isinstance(yaml.safe_load(text), dict), "invalid provider resource YAML")
            reports.append({"provider": provider, "reviewed_targets": target_counts[provider], "templates_syntax_checked": templates, "capability": capability, "result": "static_checked", "declarations": len(manifests),
                            "runtime_ready": False, "reason": "Static coverage does not establish provider/stage readiness"})
        write_json(env("REPORT"), {"schema_version": 1, "providers": reports, "capabilities_sha256": digest(registry_path), "gitops_sha": checkout_sha(gitops), "iac_sha": checkout_sha(root),
                                   "run_id": os.environ.get("GITHUB_RUN_ID", "local"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1")})
        output({"result": "static_checked", "report_sha256": digest(env("REPORT")), "gitops_sha": checkout_sha(gitops), "iac_sha": checkout_sha(root)})
    elif command == "entry-summary":
        needs = json.loads(env("NEEDS"))
        require(needs["prepare"]["result"] == "success", "matrix preparation failed")
        action = needs["prepare"]["outputs"]["action"]
        selected, other = ("self-check", "execute-iac") if action == "check" else ("execute-iac", "self-check")
        require(needs[selected]["result"] == "success" and needs[other]["result"] == "skipped", "matrix selected path failed or cancelled")
        result = needs[selected]["outputs"]
        if action == "check":
            report = read_json(env("REPORT"))
            require(digest(env("REPORT")) == result["report_sha256"], "static report digest mismatch")
            expected = set(needs["prepare"]["outputs"]["providers"].split(","))
            actual = [item["provider"] for item in report["providers"]]
            require(len(actual) == len(expected) and set(actual) == expected, "static report missing/duplicate/unexpected provider")
            require(all(item["result"] == "static_checked" for item in report["providers"]), "static provider failure")
            require(report["run_id"] == os.environ["GITHUB_RUN_ID"] and report["run_attempt"] == os.environ["GITHUB_RUN_ATTEMPT"], "stale static report")
            require(report["iac_sha"] == checkout_sha(env("ROOT")), "static checker code SHA mismatch")
            require(result["gitops_sha"] == report["gitops_sha"], "static declaration SHA mismatch")
            output({"result": "static_checked", "gitops_sha": report["gitops_sha"], "iac_sha": report["iac_sha"]})
        else:
            summary = verify_summary(env("SUMMARY"), result["receipt_sha256"], os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"],
                                     result["gitops_sha"], result["iac_sha"], env("MANIFEST"), action, env("CORRELATION") or f"{os.environ['GITHUB_RUN_ID']}:{os.environ['GITHUB_RUN_ATTEMPT']}")
            require(result["result"] == summary["result"], "workflow result differs from receipt")
            output({key: result[key] for key in ("result", "gitops_sha", "iac_sha", "receipt_sha256", "receipt_artifact_id", "inventory_artifact_id", "deploy_matrix")})
    elif command == "summary":
        context = read_json(env("CONTRACT"))
        revalidate(context, env("GITOPS_ROOT"), env("ROOT"))
        summary = summarize(context, env("EVIDENCE"), json.loads(env("NEEDS")), env("DESTINATION"))
        output({"result": summary["result"], "receipt_sha256": digest(Path(env("DESTINATION")) / "summary.json"),
                "deploy_matrix": summary["deploy_matrix"], "gitops_sha": context["gitops_sha"], "iac_sha": context["iac_sha"]})
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
                stream.write((Path(env("DESTINATION")) / "summary.md").read_text())
    elif command == "verify-summary":
        summary = verify_summary(env("SUMMARY"), env("CHECKSUM"), env("RUN_ID"), env("ATTEMPT"), env("GITOPS_SHA"), env("SHA"), env("MANIFEST"), env("ACTION"), env("CORRELATION"))
        output({"result": summary["result"], "deploy_matrix": summary["deploy_matrix"]})
    else:
        raise ContractError("unknown owner command")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except (ContractError, KeyError, ValueError, OSError) as error:
        # Avoid printing provider HTTP payloads, private file contents or subprocess stderr.
        print(f"::error::IaC contract/owner execution rejected: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
