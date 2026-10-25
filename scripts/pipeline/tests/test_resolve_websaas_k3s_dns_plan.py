import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "resolve-websaas-k3s-dns-plan.py"
spec = importlib.util.spec_from_file_location("websaas_dns_plan", MODULE)
plan_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan_module)


class WebSaasK3sDnsPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "runtime-topology.yaml"
        self.config = {
            "kind": "EdgeRoutingConfig",
            "metadata": {"environment": "prod"},
            "spec": {
                "runtime": {"routing": {"dns": {
                    "control_plane": "cloudflare-dns",
                    "canonical_records": {
                        "console.svc.plus": "console-k3s-v5.svc.plus",
                        "accounts.svc.plus": "accounts-k3s-v5.svc.plus",
                        "billing.svc.plus": "billing-k3s-v5.svc.plus",
                        "postgresql.svc.plus": "postgresql-selfhost-prod-v5.svc.plus",
                    },
                    "api_cname_records": {
                        "accounts.svc.plus": {"selfhost": "accounts-k3s-v5.svc.plus"},
                        "billing.svc.plus": {"selfhost": "billing-k3s-v5.svc.plus"},
                    },
                }}},
                "domains": {
                    "console.svc.plus": {"selfhost": "console-k3s-v5.svc.plus"},
                    "accounts.svc.plus": {"selfhost": "accounts-k3s-v5.svc.plus"},
                    "billing.svc.plus": {"selfhost": "billing-k3s-v5.svc.plus"},
                },
            },
        }

    def write_config(self):
        self.path.write_text(plan_module.yaml.safe_dump(self.config))

    def test_only_three_canonical_cnames_are_selected(self):
        self.write_config()
        plan = plan_module.resolve(self.path)
        self.assertEqual(plan["environment"], "prod")
        self.assertEqual([row["name"] for row in plan["records"]], [
            "console.svc.plus", "accounts.svc.plus", "billing.svc.plus"
        ])
        self.assertTrue(all(row["type"] == "CNAME" for row in plan["records"]))
        self.assertEqual(plan["records"][0]["expected_content"], "console-selfhost-prod-v5.svc.plus")
        self.assertEqual(plan["records"][0]["content"], "console-k3s-v5.svc.plus")

    def test_rejects_a_postgresql_or_other_target_change(self):
        self.config["spec"]["runtime"]["routing"]["dns"]["canonical_records"]["postgresql.svc.plus"] = "postgresql-k3s-v5.svc.plus"
        with self.assertRaises(ValueError):
            self.write_config()
            plan_module.resolve(self.path)


if __name__ == "__main__":
    unittest.main()
