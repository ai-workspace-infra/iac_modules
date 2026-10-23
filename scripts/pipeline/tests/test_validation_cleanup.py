"""Failure cases for candidate cleanup, without cloud credentials or mutations."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unified.contracts import ContractError, digest, validate_target
from unified.evidence import guard_plan
from unified.validation import isolated_states, state_resources, verify_retained
from unified import runtime


def state(lineage, instance_id="123", provider="linode/linode"):
    return {"lineage": lineage, "serial": 1, "resources": [
        {"mode": "managed", "module": "module.compute_candidate", "type": "linode_instance", "name": "this",
         "provider": f'provider["registry.terraform.io/{provider}"]', "instances": [{"attributes": {"id": instance_id}}]},
        {"mode": "managed", "type": "linode_firewall", "name": "fw_candidate",
         "provider": 'provider["registry.terraform.io/linode/linode"]', "instances": [{"attributes": {"id": "789"}}]},
    ]}


class ValidationCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.source = {"id": "serving", "environment": "prod", "project": "example.test", "provider": "gcp-cloud",
            "account": "source-account", "workspace": "web-saas", "auth": {"expected_identity": "source-project"},
            "stages": {"bootstrap": {"mode": "verify"}, "account": {"mode": "verify", "checks": ["network"]},
                "resources": {"mode": "terraform", "manifest": "resources/example.test/prod/gcp/source.yaml",
                    "state": {"key": "terraform/prod/example.test/gcp-cloud/source-account/web-saas/terraform.tfstate"},
                    "owners": ["module.serving"], "ownership_reviewed": True}}}
        self.target = {"id": "candidate", "environment": "prod", "project": "example.test", "provider": "akamai-cloud",
            "account": "candidate-account", "workspace": "candidate", "auth": {"expected_identity": "candidate-account"},
            "validation": {"mode": "cleanroom", "source_manifest": "iac/targets/source.yaml", "source_target": "serving",
                "destroy_owners": ["module.compute_candidate"]},
            "stages": {"bootstrap": {"mode": "verify"}, "account": {"mode": "not_applicable", "reason": "No account objects"},
                "resources": {"mode": "terraform", "manifest": "resources/example.test/prod/akamai/candidate.yaml",
                    "state": {"key": "terraform/prod/example.test/akamai-cloud/candidate-account/candidate/terraform.tfstate"},
                    "owners": ["module.compute_candidate", "linode_firewall.fw_candidate"], "protected": ["linode_firewall.fw_candidate"],
                    "ownership_reviewed": True, "destroy_allowed": True}}}
        self.resource = {"global": {"environment": "prod", "workspace": "candidate", "provider": "akamai-cloud", "account": "candidate-account", "prevent_destroy": True, "region": "test-region"},
            "hosts": [{"name": "candidate", "groups": ["generation_candidate"], "host_vars": {
                "public_dns_cutover": False, "database_background_writers": False, "source_generation": "prod-v4", "target_generation": "prod-v5"}}]}
        self.publish()

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data))

    def publish(self):
        self.write("iac/targets/source.yaml", {"apiVersion": "gitops.svc.plus/v1alpha1", "kind": "IaCPipelineTargets", "targets": [self.source]})
        self.write(self.source["stages"]["resources"]["manifest"], {"hosts": [{"name": "serving"}]})
        self.write(self.target["stages"]["resources"]["manifest"], self.resource)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)

    def validated(self):
        self.publish()
        validate_target(self.target, self.root)
        return self.target

    def plan(self):
        return {"resource_changes": [{"address": "module.compute_candidate.linode_instance.this", "mode": "managed",
            "type": "linode_instance", "change": {"actions": ["delete"], "before": {"label": "candidate", "region": "test-region", "backups_enabled": False}}}]}

    def test_protected_declaration_remains_protected(self):
        self.validated()
        source = self.root / self.target["stages"]["resources"]["manifest"]
        self.target["stages"]["resources"]["manifest_sha256"] = digest(source)
        private = self.root / "private"
        private.mkdir()
        with patch.object(runtime, "run") as runner:
            runtime.render({"action": "destroy"}, self.target, "resources", Path(__file__).resolve().parents[3], self.root, private)
        command = runner.call_args.args[0]
        self.assertIn("--allow-prod-replacement", command)
        self.assertFalse(yaml.safe_load(Path(command[command.index("--resources") + 1]).read_text())["global"]["prevent_destroy"])
        self.assertTrue(yaml.safe_load(source.read_text())["global"]["prevent_destroy"])
        normal_private = self.root / "normal-apply"
        normal_private.mkdir()
        with patch.object(runtime, "run") as normal:
            runtime.render({"action": "apply"}, self.target, "resources", Path(__file__).resolve().parents[3], self.root, normal_private)
        self.assertNotIn("--allow-prod-replacement", normal.call_args.args[0])
        self.assertEqual(Path(normal.call_args.args[0][normal.call_args.args[0].index("--resources") + 1]), source.resolve())

    def test_same_namespace_and_serving_host_fail_closed(self):
        self.target["workspace"] = "web-saas"
        with self.assertRaises(ContractError):
            self.validated()
        self.target["workspace"] = "candidate"
        self.resource["hosts"][0]["name"] = "serving"
        with self.assertRaisesRegex(ContractError, "hostname overlaps"):
            self.validated()

    def test_traffic_writers_storage_and_unprotected_declarations_rejected(self):
        for change in ("traffic", "writers", "storage", "protection"):
            with self.subTest(change=change):
                original = copy.deepcopy(self.resource)
                if change == "traffic": self.resource["hosts"][0]["host_vars"]["public_dns_cutover"] = True
                if change == "writers": self.resource["hosts"][0]["host_vars"]["database_background_writers"] = True
                if change == "storage": self.resource["volumes"] = [{"name": "data"}]
                if change == "protection": self.resource["global"]["prevent_destroy"] = False
                with self.assertRaises(ContractError): self.validated()
                self.resource = original

    def test_state_alias_and_resource_overlap_rejected_even_with_other_provider_alias(self):
        target = self.validated()
        candidate, source = state("candidate"), state("source", "456", "hashicorp/google")
        source["resources"] = source["resources"][:1]
        isolated_states(target, candidate, source)
        source["lineage"] = candidate["lineage"]
        with self.assertRaises(ContractError): isolated_states(target, candidate, source)
        source = state("source")
        source["resources"][0]["provider"] += ".other_alias"
        with self.assertRaisesRegex(ContractError, "serving source resources"): isolated_states(target, candidate, source)

    def test_cleanup_preserves_firewall_and_refuses_identity_changes(self):
        self.validated()
        before = state_resources(state("candidate"))
        after = state("candidate")
        after["resources"] = after["resources"][1:]
        verify_retained(before, after, self.target["validation"]["destroy_owners"])
        after["resources"][0]["instances"][0]["attributes"]["id"] = "changed"
        with self.assertRaises(ContractError): verify_retained(before, after, self.target["validation"]["destroy_owners"])

    def test_plan_refuses_firewall_disk_replacement_and_wrong_live_identity(self):
        target = self.validated()
        self.assertEqual(guard_plan(target, "resources", self.plan(), "destroy")["delete"], 1)
        for failure in ("firewall", "disk", "replace", "identity", "provider-backups"):
            with self.subTest(failure=failure):
                plan = self.plan()
                item = plan["resource_changes"][0]
                if failure == "firewall": item.update(address="linode_firewall.fw_candidate", type="linode_firewall")
                if failure == "disk": item["type"] = "linode_volume"
                if failure == "replace": item["change"]["actions"] = ["delete", "create"]
                if failure == "identity": item["change"]["before"]["label"] = "serving"
                if failure == "provider-backups": item["change"]["before"]["backups_enabled"] = True
                with self.assertRaises(ContractError): guard_plan(target, "resources", plan, "destroy")

    def execute_fixture(self, overlap=False, protected_delete=False):
        target = self.validated()
        context = {"action": "destroy", "stages": ["resources"], "targets": [target], "bootstrap_mode": "verify",
            **{key: "fixture" for key in ("correlation_id", "run_id", "run_attempt", "workflow_ref", "workflow_sha", "gitops_sha", "iac_sha", "contract_sha256", "manifest_sha256")},
            "requested_refs": {"iac": "fixture", "gitops": "fixture"}}
        source = state("source", "456", "hashicorp/google")
        source["resources"] = source["resources"][:1]
        if overlap: source = state("source")
        candidate = state("candidate")
        after = copy.deepcopy(candidate)
        after["resources"] = after["resources"][1:]
        plan = self.plan()
        if protected_delete:
            plan["resource_changes"].append({"address": "linode_firewall.fw_candidate", "type": "linode_firewall", "change": {"actions": ["delete"]}})
        calls, applied = [], [False]
        root = self.root / "terraform"
        root.mkdir()
        private = self.root / "execution"
        def fake_tf(directory, work, *args, **kwargs):
            calls.append((str(directory), args))
            content = b""
            if args[:2] == ("state", "pull"):
                value = source if Path(directory).name == "source-state" else after if applied[0] else candidate
                content = json.dumps(value).encode()
            elif args[:2] == ("state", "list"):
                content = "\n".join(state_resources(candidate)).encode()
            elif args[0] == "plan":
                for arg in args:
                    if arg.startswith("-out="): Path(arg[5:]).write_bytes(b"reviewed plan")
            elif args[0] == "show": content = json.dumps(plan).encode()
            elif args[0] == "apply": applied[0] = True
            return subprocess.CompletedProcess([], 0, stdout=content)
        with patch.object(runtime, "revalidate"), patch.object(runtime, "verify_identity"), patch.object(runtime, "dependencies"), patch.object(runtime, "initialize"), patch.object(runtime, "render", return_value=(root, self.root / target["stages"]["resources"]["manifest"])), patch.object(runtime, "terraform", side_effect=fake_tf):
            if overlap or protected_delete:
                with self.assertRaises(ContractError): runtime.execute(context, target["id"], "resources", self.root, self.root, self.root / "evidence", private, self.root)
                self.assertFalse(applied[0])
            else:
                receipt = runtime.execute(context, target["id"], "resources", self.root, self.root, self.root / "evidence", private, self.root)
                self.assertEqual(receipt["result"], "destroyed_verified")
                self.assertTrue(receipt["verification"]["retained_resources"])
                self.assertTrue(receipt["verification"]["source_unchanged"])
        for directory, args in calls:
            if Path(directory).name == "source-state": self.assertEqual(args, ("state", "pull"))
            if args[0] == "plan": self.assertIn("-target=module.compute_candidate", args)
            if args[0] == "apply": self.assertEqual(args[-1], str(private / "reviewed.tfplan"))

    def test_executor_applies_only_reviewed_compute_plan_and_retains_source(self):
        self.execute_fixture()

    def test_executor_stops_before_plan_or_apply_on_source_resource_overlap(self):
        self.execute_fixture(overlap=True)

    def test_executor_never_applies_a_protected_dependent_delete(self):
        self.execute_fixture(protected_delete=True)


if __name__ == "__main__":
    unittest.main()
