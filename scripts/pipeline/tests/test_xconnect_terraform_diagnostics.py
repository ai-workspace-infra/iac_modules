import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "xconnect-terraform-diagnostics.py"
SPEC = importlib.util.spec_from_file_location("xconnect_terraform_diagnostics", SCRIPT)
DIAGNOSTICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAGNOSTICS)


class XConnectTerraformDiagnosticsTests(unittest.TestCase):
    def fixture(self):
        return {"type": "diagnostic", "diagnostic": {
            "severity": "error",
            "address": "aws_instance.gateway",
            "summary": "InstanceInitiatedShutdownBehavior failed for i-private",
            "detail": "ModifyInstanceAttribute Unsupported token=private ::warning::inject",
        }}

    def test_only_fixed_labels_are_published(self):
        result = DIAGNOSTICS.summarize("apply", json.dumps(self.fixture()), 1)
        for expected in (
            "resource=aws_instance.gateway",
            "api=ModifyInstanceAttribute",
            "code=Unsupported",
            "attribute=InstanceInitiatedShutdownBehavior",
        ):
            self.assertIn(expected, result)
        for forbidden in ("i-private", "token=private", "::warning::", "\n"):
            self.assertNotIn(forbidden, result)

    def test_progress_warnings_and_unknown_provider_text_are_not_published(self):
        warning = self.fixture()
        warning["diagnostic"]["severity"] = "warning"
        raw = "\n".join((json.dumps(warning), json.dumps({
            "type": "planned_change",
            "detail": "RunInstances UnauthorizedOperation aws_instance.client secret-value",
        })))
        result = DIAGNOSTICS.summarize("plan", raw, 1)
        self.assertIn("resource=unclassified", result)
        self.assertIn("api=unclassified", result)
        self.assertIn("code=unclassified", result)
        self.assertNotIn("secret-value", result)

    def test_exact_overlapping_codes_do_not_double_classify(self):
        result = DIAGNOSTICS.summarize("init", "AccessDeniedException secret-value", 1)
        self.assertIn("code=AccessDeniedException;", result)
        self.assertNotIn("AccessDenied,AccessDeniedException", result)
        self.assertNotIn("secret-value", result)

    def test_invalid_invocation_and_oversized_logs_fail_closed(self):
        with self.assertRaises(ValueError):
            DIAGNOSTICS.summarize("apply\n::warning::inject", "", 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "terraform.log"
            log.write_bytes(b"sensitive-payload" + b"x" * DIAGNOSTICS.MAX_BYTES)
            result = subprocess.run(
                ["python3", str(SCRIPT), "apply", str(log), "1"],
                env={**os.environ, "GITHUB_STEP_SUMMARY": str(root / "missing" / "summary")},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("code=unclassified", result.stdout)
            self.assertNotIn("sensitive-payload", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
