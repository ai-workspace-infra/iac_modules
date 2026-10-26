"""Namespace membership and lifecycle now belong to GitOps; identity remains generic."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from state_contract import canonical_state_key, validate_namespace

class StateIdentityTests(unittest.TestCase):
    def test_new_declared_namespace_needs_no_code_registry_update(self):
        self.assertEqual(canonical_state_key(environment="uat", project="example.net", account="tenant-a", namespace="feature-new"), "terraform/uat/example.net/akamai-cloud/tenant-a/feature-new/terraform.tfstate")
    def test_environment_keys_are_separate(self):
        base=dict(project="example.net", account="tenant-a", namespace="feature-new")
        self.assertNotEqual(canonical_state_key(environment="uat", **base), canonical_state_key(environment="prod", **base))
    def test_shared_names_and_alias_accounts_are_rejected(self):
        for n in ("selfhost", "all", "default", "shared", "../prod", "bad/name"):
            with self.assertRaises(ValueError): validate_namespace(n)
        with self.assertRaises(ValueError): canonical_state_key(environment="uat", project="example.net", account="primary", namespace="feature-new")

if __name__ == "__main__": unittest.main()
