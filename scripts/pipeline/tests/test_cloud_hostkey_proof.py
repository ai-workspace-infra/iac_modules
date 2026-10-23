"""Full fingerprint proof across narrow consoles, without cloud credentials."""
import base64
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unified.contracts import ContractError
from unified.hostkeys import console_fingerprint


class CloudHostkeyProofTests(unittest.TestCase):
    def test_actual_bootstrap_script_produces_complete_framed_fingerprint(self):
        root = Path(__file__).resolve().parents[3]
        script = yaml.safe_load((root / "terraform-hcl-standard/akamai-cloud/templates/cloud-init.yaml").read_text())["runcmd"][-1]
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "host"
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
            result = subprocess.check_output(["sh", "-c", script.replace("/etc/ssh/ssh_host_ed25519_key.pub", str(key) + ".pub")], text=True)
            raw = base64.b64decode(Path(str(key) + ".pub").read_text().split()[1])
            expected = "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
            self.assertEqual(console_fingerprint(result), expected)
            self.assertEqual(console_fingerprint("\n".join("cloud-init[123]: " + line for line in result.splitlines())), expected)
            self.assertEqual(console_fingerprint(result + result), expected)

    def test_truncated_unframed_or_conflicting_fingerprints_fail(self):
        digest = "SHA256:" + "A" * 43
        def frame(value):
            return "IAC_ED25519_FP_BEGIN\n" + "\n".join(value[i:i+24] for i in range(0,len(value),24)) + "\nIAC_ED25519_FP_END\n"
        framed = frame(digest)
        self.assertEqual(console_fingerprint(framed), digest)
        for text in (digest, frame("SHA256:" + "A" * 32), "IAC_ED25519_FP_BEGIN\n", framed + frame("SHA256:" + "B" * 43)):
            with self.subTest(text=text), self.assertRaises(ContractError):
                console_fingerprint(text)

    def test_provider_console_reader_javascript_parses(self):
        source=Path(__file__).resolve().parents[1]/"lib/akamai-console-read.mjs"
        subprocess.run(["node","--check",str(source)],check=True,capture_output=True)


if __name__ == "__main__":
    unittest.main()
