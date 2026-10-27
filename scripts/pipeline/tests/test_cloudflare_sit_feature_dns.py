import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("feature_dns", ROOT / "cloudflare-sit-feature-dns.py")
MODULE = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FeatureDnsContract(unittest.TestCase):
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


class DnsReconcileTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.records.return_value = []
        self.client.create.return_value = {"id": "record-1"}
        self.client.update.return_value = {"id": "record-1"}
        self.name = "search-sit.onwalk.net"
        self.target = "172.237.5.48"

    def test_create_is_feature_owned_and_unproxied(self):
        result = MODULE.reconcile_record(self.client, "zone", self.name, "feature-search", self.target, lambda *_: True)
        self.assertEqual(result["action"], "create")
        payload = self.client.create.call_args.args[1]
        self.assertEqual(payload["tags"], ["feature-id:feature-search", "owner:iac-modules"])
        self.assertFalse(payload["proxied"])

    def test_adopts_only_same_target_unowned_record(self):
        original = {"id": "record-1", "type": "A", "name": self.name, "content": self.target,
                    "ttl": 300, "proxied": False, "comment": "", "tags": []}
        self.client.records.return_value = [original]
        result = MODULE.reconcile_record(self.client, "zone", self.name, "feature-search", self.target, lambda *_: True)
        self.assertEqual(result["action"], "adopt")
        self.assertEqual(self.client.update.call_args.args[2]["content"], self.target)

    def test_mismatched_unowned_record_is_never_retargeted(self):
        original = {"id": "record-1", "type": "A", "name": self.name, "content": "203.0.113.5",
                    "ttl": 300, "proxied": False, "comment": "", "tags": []}
        self.client.records.return_value = [original]
        with self.assertRaises(MODULE.base.OperationError):
            MODULE.reconcile_record(self.client, "zone", self.name, "feature-search", self.target)
        self.client.update.assert_not_called()

    def test_failed_dns_wait_restores_prior_record(self):
        original = {"id": "record-1", "type": "A", "name": self.name, "content": "203.0.113.5",
                    "ttl": 300, "proxied": False, "comment": "", "tags": ["feature-id:feature-search", "owner:iac-modules"]}
        self.client.records.side_effect = [[original], [{**original, "content": self.target, "ttl": 60,
                                                         "comment": "SIT feature lane feature-search"}]]
        with self.assertRaisesRegex(MODULE.base.OperationError, "previous DNS state restored"):
            MODULE.reconcile_record(self.client, "zone", self.name, "feature-search", self.target, lambda *_: False)
        self.assertEqual(self.client.update.call_args_list[-1].args[2]["content"], "203.0.113.5")


if __name__ == "__main__":
    unittest.main()
