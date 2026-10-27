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
    def test_stable_feature_id_maps_to_service_names(self):
        self.assertEqual(MODULE.lane_domain("feature-xconnect-referral", "console", "onwalk.net"), "xconnect-referral-sit.onwalk.net")
        self.assertEqual(MODULE.lane_domain("feature-xconnect-referral", "accounts", "onwalk.net"), "accounts-xconnect-referral-sit.onwalk.net")
        self.assertEqual(MODULE.lane_domain("feature-xconnect-referral", "billing", "onwalk.net"), "billing-xconnect-referral-sit.onwalk.net")

    def test_invalid_feature_service_and_zone_are_rejected(self):
        for feature_id, service, zone in (("../prod", "console", "onwalk.net"), ("Feature-A", "console", "onwalk.net"), ("xconnect-referral", "console", "onwalk.net"), ("feature-a-", "console", "onwalk.net"), ("feature-a", "postgresql", "onwalk.net"), ("feature-a", "console", "bad_zone"), ("feature-a", "console", "example.net")):
            with self.subTest(feature_id=feature_id, service=service, zone=zone), self.assertRaises(MODULE.base.OperationError):
                MODULE.lane_domain(feature_id, service, zone)


if __name__ == "__main__":
    unittest.main()
