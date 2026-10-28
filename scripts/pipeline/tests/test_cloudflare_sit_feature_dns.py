import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("feature_dns", ROOT / "cloudflare-sit-feature-dns.py")
MODULE = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FeatureDnsContract(unittest.TestCase):
    def test_tagged_domain_is_bound_to_feature_id_and_zone(self):
        self.assertEqual(MODULE.tagged_lane_domain('sit-test-1483', 'smoke-sit-test-1483', 'console', 'onwalk.net'), 'smoke-sit-test-1483-sit.onwalk.net')
        self.assertEqual(MODULE.tagged_lane_domain('sit-test-1483', 'smoke-sit-test-1483', 'accounts', 'onwalk.net'), 'accounts-smoke-sit-test-1483-sit.onwalk.net')
        for tag, zone in [('smoke-sit-test-1484', 'onwalk.net'), ('smoke-sit-test-1483', 'example.net')]:
            with self.subTest(tag=tag, zone=zone), self.assertRaises(MODULE.base.OperationError):
                MODULE.tagged_lane_domain('sit-test-1483', tag, 'console', zone)

    def test_stable_feature_id_maps_to_service_names(self):
        self.assertEqual(MODULE.lane_domain("feature-xconnect-referral", "console", "onwalk.net"), "xconnect-referral-sit.onwalk.net")
        self.assertEqual(MODULE.lane_domain("feature-xconnect-referral", "accounts", "onwalk.net"), "accounts-xconnect-referral-sit.onwalk.net")
        self.assertEqual(MODULE.lane_domain("feature-xconnect-referral", "billing", "onwalk.net"), "billing-xconnect-referral-sit.onwalk.net")

    def test_cmdb_target_requires_exact_dev_k3s_identity_and_public_ip(self):
        cmdb = {"dev-k3s-v5": {"ip": "172.237.5.48", "groups": ["dev", "k3s", "k3s_server", "akamai_cloud"]}}
        self.assertEqual(MODULE.dev_ingress_ip(cmdb, "dev-k3s-v5"), "172.237.5.48")
        for bad_cmdb, node in ((cmdb, "other-node"), ({"dev-k3s-v5": {"ip": "127.0.0.1", "groups": ["dev", "k3s", "k3s_server", "akamai_cloud"]}}, "dev-k3s-v5"), ({"dev-k3s-v5": {"ip": "172.237.5.48", "groups": ["all_in_one"]}}, "dev-k3s-v5")):
            with self.subTest(node=node, cmdb=bad_cmdb), self.assertRaises(MODULE.base.OperationError):
                MODULE.dev_ingress_ip(bad_cmdb, node)

    def test_invalid_feature_service_and_zone_are_rejected(self):
        for feature_id, service, zone in (("../prod", "console", "onwalk.net"), ("Feature-A", "console", "onwalk.net"), ("xconnect-referral", "console", "onwalk.net"), ("feature-a-", "console", "onwalk.net"), ("feature-a", "postgresql", "onwalk.net"), ("feature-a", "console", "bad_zone"), ("feature-a", "console", "example.net")):
            with self.subTest(feature_id=feature_id, service=service, zone=zone), self.assertRaises(MODULE.base.OperationError):
                MODULE.lane_domain(feature_id, service, zone)


if __name__ == "__main__":
    unittest.main()
