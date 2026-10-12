import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import helpers
import yaml
from generate import inventory, render, render_imports
from hcl_policy import find_violations
from guance_manifest import load_manifest, validate_manifest
from secret_scan import scan_tree



class GenerateTest(unittest.TestCase):
    def render_to(self, document=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        document = validate_manifest(document or helpers.fixture())
        render(document, Path(tmp.name))
        return document, Path(tmp.name)

    def test_one_explicit_block_per_declared_resource(self):
        document, out = self.render_to()
        text = (out / "generated_resources.tf").read_text()
        for kind, tf_type in (
            ("dashboards", "guance_dashboard"),
            ("notify_objects", "guance_notify_object"),
            ("alert_policies", "guance_alert_policy"),
            ("monitors", "guance_monitor"),
            ("mutes", "guance_mute"),
        ):
            for entry in document[kind]:
                self.assertEqual(len(re.findall(rf'^resource "{tf_type}" "{entry["id"]}" ', text, re.M)), 1)
        self.assertEqual(text.count('resource "guance_monitor"'), 3)

    def test_generated_hcl_has_no_loops_or_template_control(self):
        _, out = self.render_to()
        for path in out.glob("*.tf"):
            self.assertEqual(find_violations(path.read_text()), [], path.name)

    def test_policy_detects_forbidden_constructs(self):
        for snippet in ('  for_each = var.x', '  count = 2', '  dynamic "rule" {', 'templatefile("a", {})', '%{ for x in y }'):
            self.assertTrue(find_violations(snippet), snippet)
        self.assertEqual(find_violations('dql = "count(`x`)" # count of for_each'), [])

    def test_references_are_explicit_uuid_expressions(self):
        _, out = self.render_to()
        text = (out / "generated_resources.tf").read_text()
        self.assertIn("to     = [guance_notify_object.uat_test_receiver.uuid]", text)
        self.assertEqual(text.count("alert_policy_uuids = [guance_alert_policy.uat_default.uuid]"), 3)
        self.assertIn("alert_policy_uuid = guance_alert_policy.uat_default.uuid", text)

    def test_secrets_only_via_sensitive_variables(self):
        _, out = self.render_to()
        text = (out / "generated_resources.tf").read_text()
        self.assertIn('variable "guance_notify_uat_test_receiver_opt_set"', text)
        self.assertIn("opt_set             = jsonencode(jsondecode(var.guance_notify_uat_test_receiver_opt_set))", text)
        self.assertRegex(text, r'variable "guance_notify_uat_test_receiver_opt_set" \{\n  type      = string\n  sensitive = true')
        self.assertEqual(json.loads((out / "terraform.auto.tfvars.json").read_text()), {"guance_endpoint": "https://guance.example.invalid", "guance_region": "example-region"})
        provider = (out / "provider.tf").read_text()
        self.assertNotIn("access_token", provider)
        self.assertIn("GUANCE_ACCESS_TOKEN", provider)
        self.assertEqual(scan_tree(out), [])

    def test_monitors_stay_disabled_until_baseline_is_measured(self):
        _, out = self.render_to()
        self.assertEqual(len(re.findall(r"^  status +?= 2$", (out / "generated_resources.tf").read_text(), re.M)), 3)
        document = helpers.fixture()
        monitor = document["monitors"][0]
        monitor["baseline"] = {"status": "measured", "measured_at": "2026-10-19", "window": "7d", "source": "uat-grafana", "summary": "p95=300ms"}
        monitor["targets"][0]["dql"] = monitor["targets"][0]["dql"].replace("REPLACE_", "")
        monitor["rules"][0]["conditions"][0]["operands"] = ["5"]
        document["dashboards"][0]["template"] = {}
        _, out = self.render_to(document)
        self.assertEqual(len(re.findall(r"^  status +?= 0$", (out / "generated_resources.tf").read_text(), re.M)), 1)

    def test_pinned_provider_and_backend_contract(self):
        _, out = self.render_to()
        self.assertIn('version = "= 0.1.0"', (out / "provider.tf").read_text())
        self.assertIn('source  = "GuanceCloud/guance"', (out / "provider.tf").read_text())
        backend = (out / "backend.tf").read_text()
        for setting in ("use_lockfile                = true", "use_path_style              = true"):
            self.assertIn(setting, backend)
        for forbidden in ("access_key", "secret_key", "bucket", "endpoint"):
            self.assertNotIn(forbidden, backend.split("backend \"s3\"")[1])

    def runtime_outputs(self, document):
        ids = [e["id"] for k in ("dashboards", "notify_objects", "alert_policies", "monitors", "mutes") for e in document.get(k, [])]
        return {"cmdb_runtime": {"value": {i: {"uuid": f"uuid_{i}", "workspace_uuid": "wksp_1"} for i in ids}}}

    def test_inventory_merges_static_yaml_with_runtime_uuids(self):
        document, out = self.render_to()
        outputs = out / "outputs.json"
        outputs.write_text(json.dumps(self.runtime_outputs(document)))
        inventory(document, out, outputs)
        records = json.loads((out / "cmdb.json").read_text())["resources"]
        self.assertEqual(len(records), 7)
        by_id = {r["id"]: r for r in records}
        self.assertEqual(by_id["uat_gateway_error_rate"]["type"], "monitor")
        self.assertEqual(by_id["uat_gateway_error_rate"]["name"], "[UAT] Gateway 5xx error rate")
        self.assertEqual(by_id["uat_service_overview"]["uuid"], "uuid_uat_service_overview")
        self.assertEqual({r["environment"] for r in records}, {"uat"})
        self.assertEqual(set(records[0]), {"id", "name", "type", "environment", "workspace_alias", "uuid", "workspace_uuid"})

    def test_inventory_rejects_drift_between_manifest_and_outputs(self):
        document, out = self.render_to()
        runtime = self.runtime_outputs(document)
        runtime["cmdb_runtime"]["value"].pop("uat_default")
        (out / "o.json").write_text(json.dumps(runtime))
        with self.assertRaises(ValueError):
            inventory(document, out, out / "o.json")
        runtime = self.runtime_outputs(document)
        runtime["cmdb_runtime"]["value"]["uat_default"]["uuid"] = ""
        (out / "o.json").write_text(json.dumps(runtime))
        with self.assertRaises(ValueError):
            inventory(document, out, out / "o.json")

    def test_imports_are_explicit_blocks(self):
        document, out = self.render_to()
        existing = out / "existing.json"
        existing.write_text(json.dumps({"uat_service_overview": "dsbd_abc123", "uat_default": "altpl_abc123"}))
        render_imports(document, out, existing)
        text = (out / "generated_imports.tf").read_text()
        self.assertIn('to = guance_alert_policy.uat_default\n  id = "altpl_abc123"', text)
        self.assertIn('to = guance_dashboard.uat_service_overview\n  id = "dsbd_abc123"', text)
        self.assertEqual(find_violations(text), [])
        for bad in ({"unknown": "dsbd_abc123"}, {"uat_default": "x y"}, {}):
            existing.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                render_imports(document, out, existing)

    def test_state_key_cli(self):
        script = Path(helpers.ROOT, "scripts/generate.py")
        result = subprocess.run([sys.executable, str(script), "state-key", "--resources", str(helpers.FIXTURE)], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "terraform/uat/xworktech.com/guance-cloud/xworktech-uat/observability/terraform.tfstate")

    def test_rendering_is_deterministic(self):
        _, first = self.render_to()
        _, second = self.render_to()
        for name in ("generated_resources.tf", "terraform.auto.tfvars.json"):
            self.assertEqual((first / name).read_text(), (second / name).read_text())

    def test_env_dir_commits_only_readme_and_gitignore(self):
        ignore = Path(helpers.ROOT, "envs/uat/.gitignore").read_text().split()
        self.assertEqual(ignore, ["*", "!.gitignore", "!README.md"])


if __name__ == "__main__":
    unittest.main()
