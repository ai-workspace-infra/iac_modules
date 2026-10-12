import os
import pty
import subprocess
import tempfile
import unittest
from pathlib import Path

import helpers

SCRIPT = helpers.ROOT / "scripts/bootstrap-vault-kv.sh"
SECRET = "zz-credential-VALUE-9f3a"

FAKE_VAULT = r"""#!/usr/bin/env bash
# Minimal KV v2 CAS simulator: records argv and stdin, never prints stdin.
state="$FAKE_VAULT_DIR/versions"; touch "$state"
printf '%s\n' "$*" >> "$FAKE_VAULT_DIR/argv"
cas='' path=''
for arg in "$@"; do
  case "$arg" in -cas=*) cas="${arg#-cas=}" ;; -mount=*|kv|put) ;; *=-) ;; *) path="$arg" ;; esac
done
cat > "$FAKE_VAULT_DIR/stdin"
current="$(grep -F "$path " "$state" | awk '{print $2}' || true)"; current="${current:-0}"
[[ "$cas" == "$current" ]] || { echo "check-and-set parameter did not match the current version $SECRET_LEAK_PROBE" >&2; exit 2; }
grep -vF "$path " "$state" > "$state.new" || true; mv "$state.new" "$state"
printf '%s %s\n' "$path" "$((current + 1))" >> "$state"
"""


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        vault = self.dir / "vault"
        vault.write_text(FAKE_VAULT)
        vault.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{self.dir}:{os.environ['PATH']}", "VAULT_ADDR": "https://vault.invalid", "FAKE_VAULT_DIR": str(self.dir), "SECRET_LEAK_PROBE": SECRET}

    def run_script(self, args, answers):
        master, slave = pty.openpty()
        proc = subprocess.Popen(["bash", str(SCRIPT), *args], stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, text=True)
        os.close(slave)
        for answer in answers:
            os.write(master, (answer + "\n").encode())
        out, err = proc.communicate(timeout=30)
        os.close(master)
        return proc.returncode, out + err

    def argv(self):
        path = self.dir / "argv"
        return path.read_text() if path.exists() else ""

    def test_management_write_uses_stdin_cas_zero_and_never_echoes(self):
        code, output = self.run_script(["--env", "uat", "--workspace", "xworktech-uat", "--purpose", "management"], ["uat", SECRET])
        self.assertEqual(code, 0, output)
        self.assertNotIn(SECRET, output)
        self.assertNotIn(SECRET, self.argv())
        self.assertEqual((self.dir / "stdin").read_text(), SECRET)
        self.assertIn("-cas=0 uat/platform/observability/guance/xworktech-uat/management api_key=-", self.argv())

    def test_second_write_cannot_overwrite_without_expected_version(self):
        args = ["--env", "uat", "--workspace", "xworktech-uat", "--purpose", "query"]
        self.assertEqual(self.run_script(args, ["uat", SECRET])[0], 0)
        code, output = self.run_script(args, ["uat", SECRET + "2"])
        self.assertNotEqual(code, 0)
        self.assertNotIn(SECRET, output)  # Vault's own error text is suppressed too

    def test_rotation_requires_matching_version(self):
        base = ["--env", "uat", "--workspace", "xworktech-uat", "--purpose", "ingest"]
        self.assertEqual(self.run_script(base, ["uat", SECRET])[0], 0)
        self.assertNotEqual(self.run_script([*base, "--rotate", "--expected-version", "5"], ["uat", SECRET])[0], 0)
        self.assertEqual(self.run_script([*base, "--rotate", "--expected-version", "1"], ["uat", SECRET])[0], 0)
        self.assertIn("workspace_token=-", self.argv())

    def test_notify_record_path_and_json_check(self):
        base = ["--env", "uat", "--workspace", "xworktech-uat", "--purpose", "notify", "--object", "uat_test_receiver"]
        code, output = self.run_script(base, ["uat", "not-json"])
        self.assertNotEqual(code, 0)
        code, output = self.run_script(base, ["uat", '{"url":"https://example.invalid/h"}'])
        self.assertEqual(code, 0, output)
        self.assertIn("uat/platform/observability/guance/xworktech-uat/notify/uat_test_receiver opt_set=-", self.argv())

    def test_wrong_confirmation_cancels_before_any_write(self):
        code, _ = self.run_script(["--env", "uat", "--workspace", "xworktech-uat", "--purpose", "management"], ["prod", SECRET])
        self.assertNotEqual(code, 0)
        self.assertEqual(self.argv(), "")

    def test_argument_validation(self):
        bad = [
            ["--env", "dev", "--workspace", "w", "--purpose", "management"],
            ["--env", "uat", "--workspace", "Bad_Alias", "--purpose", "management"],
            ["--env", "uat", "--workspace", "w", "--purpose", "admin"],
            ["--env", "uat", "--workspace", "w", "--purpose", "notify"],
            ["--env", "uat", "--workspace", "w", "--purpose", "management", "--object", "x"],
            ["--env", "uat", "--workspace", "w", "--purpose", "management", "--expected-version", "2"],
            ["--env", "uat", "--workspace", "w", "--purpose", "management", "--rotate"],
        ]
        for args in bad:
            result = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=self.env, stdin=subprocess.DEVNULL)
            self.assertEqual(result.returncode, 2, args)

    def test_requires_a_terminal(self):
        result = subprocess.run(["bash", str(SCRIPT), "--env", "uat", "--workspace", "w", "--purpose", "management"], capture_output=True, text=True, env=self.env, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 1)
        self.assertIn("interactively", result.stderr)


if __name__ == "__main__":
    unittest.main()
