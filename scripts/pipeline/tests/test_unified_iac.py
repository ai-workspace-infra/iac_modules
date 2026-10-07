"""Offline failure/identity/state/evidence contracts, with no cloud credentials."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unified.contracts import ContractError, PROVIDERS, STAGES, digest, prepare, revalidate, state_lock_key, write_json
from unified.evidence import collect, guard_plan, receipt_base, sanitize_inventory, summarize, verify_summary
from unified import runtime, auth
import unified_cli


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.gitops, self.iac = self.root / "gitops", self.root / "iac"
        for root in (self.gitops, self.iac):
            root.mkdir()
            git(root, "init", "-q")
            git(root, "config", "user.name", "Contract Test")
            git(root, "config", "user.email", "test@example.invalid")
            (root / "README.md").write_text("fixture\n")
            git(root, "add", ".")
            git(root, "commit", "-qm", "fixture")
        self.target = {
            "id": "uat-akamai-web-saas", "environment": "uat", "project": "svc.plus",
            "provider": "akamai-cloud", "account": "concrete-account", "workspace": "web-saas",
            "auth": {"expected_identity": "concrete-account", "vault_role": "github-actions-platform-ops-toolkit-uat"},
            "stages": {
                "bootstrap": {"mode": "verify"},
                "account": {"mode": "not_applicable", "reason": "No independent account objects"},
                "resources": {"mode": "terraform", "manifest": "resources/svc.plus/uat/akamai/web-saas.yaml",
                    "state": {"key": "terraform/uat/svc.plus/akamai-cloud/concrete-account/web-saas/terraform.tfstate", "cli_workspace": "default"},
                    "owners": ["module.compute_web_saas", "linode_firewall.fw_web_saas"],
                    "ownership_reviewed": True, "protected": [], "destroy_allowed": True},
            },
        }
        self.manifest = "iac/targets/uat.yaml"
        self.publish([self.target])

    def publish(self, targets):
        source = self.gitops / self.manifest
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(yaml.safe_dump({"apiVersion": "gitops.svc.plus/v1alpha1", "kind": "IaCPipelineTargets", "targets": targets}))
        for target in targets:
            for spec in target["stages"].values():
                if spec.get("manifest"):
                    path = self.gitops / spec["manifest"]
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("hosts: []\n")
        git(self.gitops, "add", ".")
        git(self.gitops, "commit", "--allow-empty", "-qm", "declare fixture")

    def context(self, action="apply", scope="resources"):
        return prepare(self.gitops, self.iac, self.manifest, "uat", action, scope, "verify", "correlation", {"iac": "main", "gitops": "main"})

    def stage_receipt(self, context, stage="resources", result=None):
        target = context["targets"][0]
        receipt = receipt_base(context, target, stage)
        receipt.update(result=result or {"apply": "applied_verified", "plan": "planned", "destroy": "destroyed_verified"}[context["action"]], plan_sha256="a" * 64)
        receipt["verification"] = {"identity": True, "contract": True, "cleanup": True, "ownership": True, "convergence": True}
        if target["stages"][stage]["mode"] == "not_applicable":
            receipt.update(result="not_applicable", reason=target["stages"][stage]["reason"])
        return receipt

    def needs(self, context):
        result = {"prepare": {"result": "success"}}
        for stage in STAGES:
            for job in (stage, "destroy-" + stage):
                selected = ("destroy-" + stage if context["action"] == "destroy" else stage) in (
                    ["destroy-" + s for s in context["stages"]] if context["action"] == "destroy" else context["stages"])
                result[job] = {"result": "success" if selected and job == ("destroy-" + stage if context["action"] == "destroy" else stage) else "skipped"}
        return result

    def test_namespace_lock_survives_target_id_alias(self):
        renamed = copy.deepcopy(self.target)
        renamed["id"] = "other-manifest-id"
        self.assertEqual(state_lock_key(renamed), state_lock_key(self.target))
        renamed["account"] = "different-account"
        self.assertNotEqual(state_lock_key(renamed), state_lock_key(self.target))

    def test_real_provider_identity_mismatch_rejected(self):
        fixtures = [
            ("aws-cloud", {"Account": "wrong", "Arn": "arn:aws:sts::wrong:assumed-role/deploy/run"}),
            ("azure-cloud", {"id": "wrong", "tenantId": "tenant"}),
            ("gcp-cloud", {"projectId": "wrong"}),
        ]
        for provider, response in fixtures:
            target = copy.deepcopy(self.target)
            target["provider"] = provider
            target["auth"]["tenant"] = "tenant"
            with self.subTest(provider=provider), patch.object(auth, "command_json", return_value=response), self.assertRaises(ContractError):
                auth.verify_identity(target)
        for provider, response in (("vultr-vps", {"account": {"email": "wrong"}}), ("akamai-cloud", {"username": "wrong"})):
            target = copy.deepcopy(self.target)
            target["provider"] = provider
            with self.subTest(provider=provider), patch.dict(os.environ, {"VULTR_API_KEY": "fixture", "LINODE_TOKEN": "fixture"}), patch.object(auth, "request_json", return_value=response), self.assertRaises(ContractError):
                auth.verify_identity(target)

    def test_ucloud_prerequisites_use_documented_fields_and_paginate(self):
        target = copy.deepcopy(self.target)
        target["provider"] = "ucloud"
        responses = [{"DataSet": [{"FWId": "fw-owned"}]}, {"KeyPairs": [{"KeyPairId": "other", "ProjectId": target["account"]}], "TotalCount": 2}, {"KeyPairs": [{"KeyPairId": "key-owned", "ProjectId": target["account"]}], "TotalCount": 2}]
        with patch.dict(os.environ, {"UCLOUD_REGION": "cn-test", "TF_VAR_ucloud_bootstrap_security_group_id": "fw-owned", "TF_VAR_ucloud_bootstrap_key_pair_id": "key-owned"}), patch.object(auth, "ucloud", side_effect=responses) as api:
            auth.verify_checks(target, [{"kind": "ucloud-firewall"}, {"kind": "ucloud-key-pair"}])
        self.assertEqual(api.call_args_list[0].args[1]["FWId"], "fw-owned")
        self.assertEqual(api.call_args_list[1].args[0], "DescribeUHostKeyPairs")
        self.assertEqual(api.call_args_list[2].args[1]["Offset"], 1)

    def test_static_entry_summary_fails_closed_on_stale_duplicate_or_failed_job(self):
        report = self.root / "static.json"
        data = {"providers": [{"provider": p, "result": "static_checked"} for p in PROVIDERS], "run_id": "42", "run_attempt": "2", "iac_sha": git(self.iac, "rev-parse", "HEAD"), "gitops_sha": git(self.gitops, "rev-parse", "HEAD")}
        needs = {"prepare": {"result": "success", "outputs": {"action": "check", "providers": ",".join(PROVIDERS)}}, "self-check": {"result": "success", "outputs": {}}, "execute-iac": {"result": "skipped"}}
        env = {"IAC_ROOT": str(self.iac), "IAC_REPORT": str(report), "GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "2"}
        for defect in (None, "stale", "duplicate", "failed", "cancelled"):
            sample, jobs = copy.deepcopy(data), copy.deepcopy(needs)
            if defect == "stale": sample["run_attempt"] = "1"
            if defect == "duplicate": sample["providers"][0] = sample["providers"][1]
            if defect in {"failed", "cancelled"}: jobs["self-check"]["result"] = defect
            write_json(report, sample)
            jobs["self-check"]["outputs"].update(report_sha256=digest(report), gitops_sha=sample["gitops_sha"])
            with self.subTest(defect=defect), patch.dict(os.environ, dict(env, IAC_NEEDS=json.dumps(jobs))):
                if defect:
                    with self.assertRaises(ContractError): unified_cli.main("entry-summary")
                else: unified_cli.main("entry-summary")

    def test_static_check_without_declared_capabilities_fails(self):
        with patch.dict(os.environ, {"IAC_ROOT": str(self.iac), "IAC_GITOPS_ROOT": str(self.gitops), "IAC_REPORT": str(self.root / "report.json")}):
            with self.assertRaises(ContractError): unified_cli.main("self-check")

    def test_inventory_rejects_ini_injection_and_loopback(self):
        for sample in ({"host\n[unsafe]": {"ip": "192.0.2.1"}}, {"host": {"ip": "127.0.0.1"}}, {"host": {"ip": "192.0.2.1", "groups": ["group\n[unsafe]"]}}):
            with self.subTest(sample=sample), self.assertRaises(ContractError): sanitize_inventory(sample)

    def test_missing_gitops_source_fails(self):
        with self.assertRaises(ContractError):
            prepare(self.gitops, self.iac, "missing.yaml", "uat", "apply", "resources", "verify", "", {})

    def test_gitops_traversal_and_untracked_sources_rejected(self):
        for source in ("../outside.yaml", "/tmp/config.yaml", "untracked.yaml"):
            with self.subTest(source=source), self.assertRaises(ContractError):
                prepare(self.gitops, self.iac, source, "uat", "apply", "resources", "verify", "", {})

    def test_fixed_sha_and_digest_rechecked(self):
        context = self.context()
        self.assertEqual(revalidate(context, self.gitops, self.iac), context)
        (self.gitops / self.manifest).write_text("tampered")
        with self.assertRaises(ContractError):
            revalidate(context, self.gitops, self.iac)

    def test_identity_override_and_contract_tampering_rejected(self):
        context = self.context()
        context["targets"][0]["account"] = "another-account"
        with self.assertRaises(ContractError):
            revalidate(context, self.gitops, self.iac)

    def test_environment_cannot_override_declaration(self):
        with self.assertRaises(ContractError):
            prepare(self.gitops, self.iac, self.manifest, "prod", "apply", "resources", "verify", "", {})

    def test_duplicate_target_or_shared_state_rejected(self):
        for change_id in (False, True):
            target = copy.deepcopy(self.target)
            if change_id:
                target["id"] = "other-target"
            self.publish([self.target, target])
            with self.assertRaises(ContractError):
                self.context()

    def test_state_key_and_cli_workspace_not_renamed(self):
        for change in ({"key": "terraform/uat/other/state.tfstate"}, {"cli_workspace": "uat-new"}):
            target = copy.deepcopy(self.target)
            target["stages"]["resources"]["state"].update(change)
            self.publish([target])
            with self.assertRaises(ContractError):
                self.context()

    def test_six_providers_have_explicit_contract_and_unsupported_fails_execution(self):
        for provider in PROVIDERS:
            target = copy.deepcopy(self.target)
            target["provider"] = provider
            target["stages"]["resources"] = {"mode": "unsupported", "reason": "ownership/state split pending"}
            if provider not in {"vultr-vps", "akamai-cloud"}:
                target["stages"]["account"] = {"mode": "unsupported", "reason": "account adapter pending"}
            self.publish([target])
            with self.subTest(provider=provider):
                self.assertEqual(self.context("check")["targets"][0]["provider"], provider)
                with self.assertRaises(ContractError):
                    self.context("apply")

    def test_forward_and_destroy_orders_are_independent(self):
        self.assertEqual(self.context("plan", "all")["stages"], list(STAGES))
        # Shared bootstrap is protected: all destroy must reject rather than retire it.
        with self.assertRaises(ContractError):
            self.context("destroy", "all")
        self.assertEqual(self.context("destroy")["stages"], ["resources"])

    def test_reconcile_scope_explicit(self):
        with self.assertRaises(ContractError):
            prepare(self.gitops, self.iac, self.manifest, "uat", "apply", "resources", "reconcile", "", {})

    def test_destroy_shared_or_external_reference_blocked(self):
        for protection in ({"shared": True}, {"backend": True}, {"management_identity": True}, {"external_references": ["other-workload"]}, {"destroy_allowed": False}):
            target = copy.deepcopy(self.target)
            target["stages"]["resources"].update(protection)
            self.publish([target])
            with self.subTest(protection=protection), self.assertRaises(ContractError):
                self.context("destroy")

    def test_empty_missing_duplicate_corrupt_old_or_wrong_receipt_fails(self):
        context = self.context()
        evidence = self.root / "receipts"
        evidence.mkdir()
        with self.assertRaises(ContractError):
            collect(context, evidence)
        for field in ("run_id", "run_attempt", "gitops_sha", "iac_sha", "account", "manifest_sha256", "contract_sha256", "stage"):
            receipt = self.stage_receipt(context)
            receipt[field] = "wrong"
            write_json(evidence / "one" / "receipt.json", receipt)
            with self.subTest(field=field), self.assertRaises(ContractError):
                collect(context, evidence)
        write_json(evidence / "one" / "receipt.json", self.stage_receipt(context))
        write_json(evidence / "two" / "receipt.json", self.stage_receipt(context))
        with self.assertRaises(ContractError):
            collect(context, evidence)
        (evidence / "two" / "receipt.json").unlink()
        (evidence / "one" / "receipt.json").write_text("{bad")
        with self.assertRaises(ValueError):
            collect(context, evidence)

    def test_receipt_cleanup_convergence_and_inventory_required(self):
        context = self.context()
        evidence = self.root / "receipt"
        for field in ("cleanup", "identity", "ownership", "convergence", "contract"):
            receipt = self.stage_receipt(context)
            receipt["verification"][field] = False
            write_json(evidence / "receipt.json", receipt)
            with self.subTest(field=field), self.assertRaises(ContractError):
                collect(context, evidence)
        receipt = self.stage_receipt(context)
        receipt["inventory_sha256"] = "a" * 64
        write_json(evidence / "receipt.json", receipt)
        with self.assertRaises(ContractError):
            collect(context, evidence)

    def test_plan_is_not_apply_acceptance(self):
        context = self.context("apply")
        write_json(self.root / "receipt.json", self.stage_receipt(context, result="planned"))
        with self.assertRaises(ContractError):
            collect(context, self.root)

    def test_full_summary_and_consumer_exact_binding(self):
        context = self.context()
        evidence, destination = self.root / "receipts", self.root / "summary"
        receipt = self.stage_receipt(context)
        write_json(evidence / "inventory.json", {"host.example.invalid": {"instance_id": "known", "ip": "192.0.2.1"}})
        receipt["inventory_sha256"] = digest(evidence / "inventory.json")
        write_json(evidence / "receipt.json", receipt)
        result = summarize(context, evidence, self.needs(context), destination)
        args = [destination / "summary.json", digest(destination / "summary.json"), context["run_id"], context["run_attempt"], context["gitops_sha"], context["iac_sha"], self.manifest, "apply", "correlation"]
        self.assertEqual(verify_summary(*args), result)
        write_json(destination / "inventory.json", {})
        with self.assertRaises(ContractError):
            verify_summary(*args)

    def test_failure_cancelled_and_upstream_skips_block_summary(self):
        context = self.context()
        evidence = self.root / "receipts"
        write_json(evidence / "receipt.json", self.stage_receipt(context))
        for failed in ("failure", "cancelled", "skipped"):
            needs = self.needs(context)
            needs["resources"]["result"] = failed
            with self.subTest(result=failed), self.assertRaises(ContractError):
                summarize(context, evidence, needs, self.root / "summary")
        context = self.context("apply", "all")
        needs = self.needs(context)
        needs["bootstrap"]["result"] = "failure"
        needs["account"]["result"] = "skipped"
        with self.assertRaises(ContractError):
            summarize(context, evidence, needs, self.root / "summary")

    def test_plan_guards_owned_protected_persistent_and_replace(self):
        def change(address="module.compute_web_saas.linode_instance.this", actions=None, kind="linode_instance"):
            return {"resource_changes": [{"address": address, "type": kind, "change": {"actions": actions or ["create"]}}]}
        self.assertEqual(guard_plan(self.target, "resources", change(), "apply")["create"], 1)
        for plan, action in ((change("module.other.linode_instance.this"), "apply"), (change(actions=["delete", "create"]), "apply"), (change(actions=["delete"], kind="linode_volume"), "destroy")):
            with self.assertRaises(ContractError):
                guard_plan(self.target, "resources", plan, action)
        self.target["stages"]["resources"]["protected"] = ["module.compute_web_saas"]
        with self.assertRaises(ContractError):
            guard_plan(self.target, "resources", change(actions=["delete"]), "destroy")

    def test_sanitization_does_not_copy_credential_host_vars(self):
        raw = {"host": {"ip": "192.0.2.1", "password": "should-not-copy", "host_vars": {"secret": "should-not-copy", "service_domains": ["example.invalid"]}}}
        self.assertNotIn("should-not-copy", json.dumps(sanitize_inventory(raw)))

    def test_resources_only_verifies_existing_dependencies(self):
        context = self.context()
        with patch.object(runtime, "verify_identity") as identity:
            runtime.dependencies(context, context["targets"][0], "resources", self.root)
            identity.assert_called_once()
        context["targets"][0]["stages"]["account"] = {"mode": "unsupported", "reason": "pending"}
        with patch.object(runtime, "verify_identity"), self.assertRaises(ContractError):
            runtime.dependencies(context, context["targets"][0], "resources", self.root)

    def test_apply_consumes_same_saved_plan_and_failed_inventory_never_green(self):
        context = self.context()
        private, evidence = self.root / "private", self.root / "evidence"
        root = self.root / "terraform"
        root.mkdir()
        calls = []
        def fake_tf(directory, work, *args, **kwargs):
            calls.append(args)
            if args[0] == "plan":
                for arg in args:
                    if arg.startswith("-out="):
                        Path(arg[5:]).write_bytes(b"saved plan")
            content = json.dumps({"resource_changes": [{"address": "module.compute_web_saas.linode_instance.this", "type": "linode_instance", "change": {"actions": ["create"]}}]}).encode() if args[0] == "show" else b""
            return subprocess.CompletedProcess([], 0, stdout=content)
        with patch.object(runtime, "verify_identity"), patch.object(runtime, "render", return_value=(root, self.gitops / self.manifest)), patch.object(runtime, "initialize"), patch.object(runtime, "terraform", side_effect=fake_tf), patch.object(runtime, "run", side_effect=ContractError("inventory failed")):
            with self.assertRaises(ContractError):
                runtime.execute(context, self.target["id"], "resources", self.iac, self.gitops, evidence, private, self.root)
        apply = next(args for args in calls if args[0] == "apply")
        self.assertEqual(apply[-1], str(private / "reviewed.tfplan"))
        self.assertEqual(json.loads((evidence / "receipt.json").read_text())["result"], "failed")
        self.assertFalse(any("import" in args or "destroy" == args[0] or any("migrate-state" in arg for arg in args) for args in calls))


if __name__ == "__main__":
    unittest.main()
