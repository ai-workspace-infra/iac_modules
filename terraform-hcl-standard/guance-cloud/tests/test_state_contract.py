import unittest

import helpers  # noqa: F401
from state_contract import canonical_state_key


class StateContractTest(unittest.TestCase):
    def test_canonical_key(self):
        key = canonical_state_key(environment="uat", project="xworktech.com", account="xworktech-uat")
        self.assertEqual(key, "terraform/uat/xworktech.com/guance-cloud/xworktech-uat/observability/terraform.tfstate")

    def test_uat_and_prod_never_share_a_key(self):
        uat = canonical_state_key(environment="uat", project="p", account="a-uat")
        prod = canonical_state_key(environment="prod", project="p", account="a-prod")
        self.assertNotEqual(uat, prod)

    def test_account_aliases_and_shared_namespaces_are_rejected(self):
        for account in ("primary", "default", "main"):
            with self.assertRaises(ValueError):
                canonical_state_key(environment="uat", project="p", account=account)
        for namespace in ("shared", "all"):
            with self.assertRaises(ValueError):
                canonical_state_key(environment="uat", project="p", account="a", namespace=namespace)

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            canonical_state_key(environment="uat", project="../x", account="a")


if __name__ == "__main__":
    unittest.main()
