import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = (ROOT / "scripts" / "generate.py").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "open-platform.tf.j2").read_text(encoding="utf-8")


class OSLoginWithoutIAPTest(unittest.TestCase):
    def test_manifest_can_enable_oslogin_without_iap(self):
        self.assertIn('"enable_oslogin": spec.get("enable_oslogin", spec.get("enable_iap_ssh", False))', GENERATOR)
        self.assertIn('if not isinstance(global_config["enable_oslogin"], bool)', GENERATOR)
        self.assertIn('enable_oslogin = {{ enable_oslogin | tojson }}', TEMPLATE)
        self.assertIn('''"enable_iap_ssh": spec.get("enable_iap_ssh", False)''', GENERATOR)
        self.assertIn('{% if vault_nodes and enable_oslogin %}', TEMPLATE)
        self.assertIn('{% if vault_nodes and enable_iap_ssh %}', TEMPLATE)


if __name__ == "__main__":
    unittest.main()
