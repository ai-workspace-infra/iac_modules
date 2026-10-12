import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401
from secret_scan import scan_keys, scan_text, scan_tree


class SecretScanTest(unittest.TestCase):
    def test_patterns(self):
        self.assertIn("chat-webhook", scan_text("https://oapi.dingtalk" + ".com/robot/send?" + "access_token=abcdefgh12345"))
        self.assertIn("token-query", scan_text("https://x.invalid/hook?" + "token=abcdefgh1234"))
        self.assertIn("vault-token", scan_text("hv" + "s." + "A" * 24))
        self.assertIn("private-key", scan_text("-----BEGIN RSA " + "PRIVATE KEY-----"))
        self.assertEqual(scan_text("resource guance_dashboard x {}"), [])

    def test_keys(self):
        self.assertEqual(scan_keys({"a": [{"webhook": "x"}]}), ["$.a[0].webhook"])

    def test_tree_reports_files_without_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.tf").write_text("url = \"https://hooks.slack" + ".com/services/T/B/x\"")
            Path(tmp, "b.tf").write_text("ok")
            self.assertEqual(scan_tree(tmp), [("a.tf", "chat-webhook")])


if __name__ == "__main__":
    unittest.main()
