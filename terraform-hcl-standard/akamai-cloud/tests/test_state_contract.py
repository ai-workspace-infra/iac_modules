import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from state_contract import (  # noqa: E402
    CLEANUP_NAMESPACES,
    UAT_NAMESPACES,
    canonical_state_key,
    may_destroy,
    validate_namespace,
)


class StateContractTest(unittest.TestCase):
    def test_uat_namespaces_have_unique_keys(self):
        keys = {
            canonical_state_key(
                environment="uat",
                project="svc.plus",
                account="manbuzhe2026",
                namespace=namespace,
            )
            for namespace in UAT_NAMESPACES
        }

        self.assertEqual(len(UAT_NAMESPACES), 12)
        self.assertEqual(len(keys), 12)
        self.assertTrue(all("/selfhost/" not in key for key in keys))

    def test_cleanup_excludes_persistent_open_platform(self):
        self.assertEqual(len(CLEANUP_NAMESPACES), 10)
        self.assertFalse(may_destroy("open-platform"))
        self.assertFalse(may_destroy("web-saas-k3s-v5"))
        self.assertNotIn("open-platform", CLEANUP_NAMESPACES)
        for namespace in CLEANUP_NAMESPACES:
            self.assertTrue(may_destroy(namespace))

    def test_k3s_validation_state_is_separate_from_v5(self):
        target = canonical_state_key(environment="uat", project="svc.plus", account="manbuzhe2026", namespace="web-saas-k3s-v5")
        source = canonical_state_key(environment="prod", project="svc.plus", account="manbuzhe2026", namespace="web-saas-prod-v5")
        self.assertNotEqual(target, source)
        self.assertNotIn("web-saas-k3s-v5", CLEANUP_NAMESPACES)

    def test_shared_namespaces_are_rejected(self):
        for namespace in ("selfhost", "all", "default", "shared"):
            with self.subTest(namespace=namespace):
                with self.assertRaises(ValueError):
                    validate_namespace(namespace)

    def test_account_alias_is_rejected(self):
        with self.assertRaises(ValueError):
            canonical_state_key(
                environment="uat",
                project="svc.plus",
                account="primary",
                namespace="web-saas",
            )

    def test_old_observability_source_is_not_a_namespace(self):
        self.assertNotIn("observability.svc.plus", UAT_NAMESPACES)
        with self.assertRaises(ValueError):
            validate_namespace("observability.svc.plus")


if __name__ == "__main__":
    unittest.main()
