"""Provider-schema validation of the rendered fixture. Skipped when terraform (>= 1.10) is unavailable."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import helpers
from generate import render
from guance_manifest import load_manifest

TERRAFORM = os.environ.get("TERRAFORM") or shutil.which("terraform")


@unittest.skipUnless(TERRAFORM, "terraform not installed")
class TerraformOfflineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        render(load_manifest(helpers.FIXTURE), cls.dir)
        cls.run_tf("init", "-backend=false", "-input=false", "-no-color")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def run_tf(cls, *args):
        return subprocess.run([TERRAFORM, f"-chdir={cls.dir}", *args], capture_output=True, text=True, check=False)

    def test_fmt_has_no_diff(self):
        result = self.run_tf("fmt", "-check", "-diff", "-no-color")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_validate_against_pinned_provider_schema(self):
        result = self.run_tf("validate", "-no-color")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_lock_file_pins_0_1_0(self):
        lock = (self.dir / ".terraform.lock.hcl").read_text()
        self.assertIn('provider "registry.terraform.io/guancecloud/guance"', lock)
        self.assertIn('version     = "0.1.0"', lock)


if __name__ == "__main__":
    unittest.main()
