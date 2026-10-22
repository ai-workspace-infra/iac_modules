import unittest

import helpers  # noqa: F401
from hcl import Raw, hcl_body, to_hcl


class HclTest(unittest.TestCase):
    def test_scalars_and_escaping(self):
        self.assertEqual(to_hcl(None), "null")
        self.assertEqual(to_hcl(True), "true")
        self.assertEqual(to_hcl(3), "3")
        self.assertEqual(to_hcl("a${b}%{c}"), '"a$${b}%%{c}"')

    def test_raw_reference_is_verbatim(self):
        self.assertEqual(to_hcl([Raw("guance_notify_object.x.uuid")]), "[guance_notify_object.x.uuid]")

    def test_body_aligns_single_line_groups_only(self):
        body = hcl_body({"a": 1, "bbb": 2, "cc": {"z": 1}, "d": 4})
        self.assertEqual(body.splitlines()[:2], ["  a   = 1", "  bbb = 2"])
        self.assertIn("  cc = {", body)
        self.assertIn("  d = 4", body)

    def test_unsupported_type_is_rejected(self):
        with self.assertRaises(TypeError):
            to_hcl(object())


if __name__ == "__main__":
    unittest.main()
