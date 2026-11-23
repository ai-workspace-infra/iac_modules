"""Offline unit and contract tests for client-mirrors dual-mirror IaC."""

import io
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
CLIENT_MIRRORS_ROOT = TESTS_DIR.parent
SCRIPTS_DIR = CLIENT_MIRRORS_ROOT / "scripts"
FIXTURE = TESTS_DIR / "fixtures" / "mirrors.yaml"

sys.path.insert(0, str(SCRIPTS_DIR))
import ensure_aliyun_cdn_verify_txt as verify_txt  # noqa: E402
import generate  # noqa: E402
import probe_dual_mirrors as probe  # noqa: E402


class _FakeHTTPResponse:
    def __init__(self, status=200, body=b"{}", headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class ClientMirrorsIaCTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="client-mirrors-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_check_hcl_passes_on_repository_tree(self):
        self.assertEqual(generate.check_hcl_tree(CLIENT_MIRRORS_ROOT), [])

    def test_render_produces_flat_hcl_and_no_secret_values(self):
        workdir = self.tmp / "workdir"
        rc = generate.main(["render", "--resources", str(FIXTURE), "--workdir", str(workdir)])
        self.assertEqual(rc, 0)

        generated = (workdir / "generated_mirrors.tf").read_text(encoding="utf-8")
        self.assertIn('module "global_r2"', generated)
        self.assertIn('module "cn_oss_cdn"', generated)
        self.assertIn('cdn_scope            = "overseas"', generated)
        self.assertIn('oss_region           = "cn-hongkong"', generated)
        self.assertEqual(generate.check_hcl_tree(workdir), [])

        tfvars = json.loads((workdir / "terraform.auto.tfvars.json").read_text(encoding="utf-8"))
        self.assertEqual(tfvars, {"alicloud_region": "cn-hongkong", "zone_name": "svc.plus"})

        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc2 = generate.main(["state-key", "--resources", str(FIXTURE)])
        self.assertEqual(rc2, 0)
        self.assertEqual(
            buf.getvalue().strip(),
            "terraform/prod/svc.plus/client-mirrors/svc-plus-prod/mirrors/terraform.tfstate",
        )

    def test_manifest_rejects_secret_like_keys_and_values(self):
        bad_yaml = FIXTURE.read_text(encoding="utf-8") + "\n  extra:\n    api_token: plain\n"
        bad_path = self.tmp / "bad.yaml"
        bad_path.write_text(bad_yaml, encoding="utf-8")
        with self.assertRaises(ValueError):
            generate.load_and_validate_manifest(bad_path)

    def test_vault_sync_writes_stdin_json_and_never_prints_secrets(self):
        tf_out = self.tmp / "tf_out.json"
        r2_secret = "r2-super-secret-sha256-value"
        ali_secret = "ali-super-secret-ram-value"
        tf_out.write_text(
            json.dumps(
                {
                    "mirror_credentials": {
                        "value": {
                            "cloudflare_r2": {
                                "vault_kv_path": "prod/platform/storage/cloudflare-r2",
                                "data": {
                                    "access_key_id": "r2-key-id-123",
                                    "secret_access_key": r2_secret,
                                    "bucket": "svc-plus-releases-global",
                                    "endpoint": "https://acct.r2.cloudflarestorage.com",
                                    "custom_domain": "dl.svc.plus",
                                },
                            },
                            "aliyun_oss": {
                                "vault_kv_path": "prod/platform/storage/aliyun-oss",
                                "data": {
                                    "access_key_id": "LTAI5testkeyid",
                                    "access_key_secret": ali_secret,
                                    "bucket": "svc-plus-releases-cn-hk",
                                    "endpoint": "https://oss-cn-hongkong.aliyuncs.com",
                                    "cdn_domain": "cn-dl.svc.plus",
                                    "oss_region": "cn-hongkong",
                                    "cdn_scope": "overseas",
                                },
                            },
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        capture_dir = self.tmp / "captured"
        capture_dir.mkdir()
        fake_vault = self.tmp / "vault"
        fake_vault.write_text(
            f"""#!/usr/bin/env python3
import sys
from pathlib import Path
Path({str(capture_dir)!r} + "/" + str(len(list(Path({str(capture_dir)!r}).iterdir()))) + ".txt").write_text(
    " ".join(sys.argv[1:]) + "\\n" + sys.stdin.read()
)
""",
            encoding="utf-8",
        )
        fake_vault.chmod(fake_vault.stat().st_mode | stat.S_IXUSR)

        out_buf = io.StringIO()
        with mock.patch("sys.stdout", out_buf):
            rc = generate.main(
                ["vault-sync", "--tf-output-json", str(tf_out), "--vault-bin", str(fake_vault)]
            )
        self.assertEqual(rc, 0)
        stdout = out_buf.getvalue()
        self.assertNotIn(r2_secret, stdout)
        self.assertNotIn(ali_secret, stdout)
        self.assertIn("prod/platform/storage/cloudflare-r2", stdout)
        self.assertIn("prod/platform/storage/aliyun-oss", stdout)

        writes = sorted(capture_dir.iterdir())
        self.assertEqual(len(writes), 2)
        first = writes[0].read_text(encoding="utf-8")
        self.assertIn("kv put -mount=kv prod/platform/storage/cloudflare-r2 -", first)
        self.assertIn(r2_secret, first)
        second = writes[1].read_text(encoding="utf-8")
        self.assertIn("kv put -mount=kv prod/platform/storage/aliyun-oss -", second)
        self.assertIn(ali_secret, second)

    def test_ensure_aliyun_cdn_verify_txt_creates_missing_record(self):
        calls = []

        def fake_opener(req, timeout=20):
            calls.append((req.get_method(), req.full_url, req.data))
            if "DescribeVerifyContent" in req.full_url:
                return _FakeHTTPResponse(body=json.dumps({"Content": "aliyun-cdn-verify-token"}).encode())
            if "/zones?name=svc.plus" in req.full_url:
                return _FakeHTTPResponse(body=json.dumps({"success": True, "result": [{"id": "zone-123"}]}).encode())
            if "/dns_records?type=TXT" in req.full_url:
                return _FakeHTTPResponse(body=json.dumps({"success": True, "result": []}).encode())
            if req.get_method() == "POST" and "/dns_records" in req.full_url:
                return _FakeHTTPResponse(body=json.dumps({"success": True, "result": {"id": "rec-1"}}).encode())
            if "VerifyDomainOwner" in req.full_url:
                return _FakeHTTPResponse(body=json.dumps({"Content": "ok"}).encode())
            raise AssertionError(f"Unexpected request: {req.get_method()} {req.full_url}")

        res = verify_txt.ensure_verify_txt(
            cdn_domain="cn-dl.svc.plus",
            zone_name="svc.plus",
            alicloud_access_key="ak",
            alicloud_secret_key="sk",
            cloudflare_api_token="cf-token",
            wait_dns_seconds=0,
            opener=fake_opener,
        )
        self.assertEqual(res["action"], "created")
        self.assertTrue(res["verified"])
        post_calls = [c for c in calls if c[0] == "POST"]
        self.assertEqual(len(post_calls), 1)
        payload = json.loads(post_calls[0][2].decode("utf-8"))
        self.assertEqual(payload["name"], "verification.svc.plus")
        self.assertEqual(payload["type"], "TXT")
        self.assertEqual(payload["content"], '"aliyun-cdn-verify-token"')

    def test_probe_dual_mirrors_checks_http_200_and_cors(self):
        def ok_opener(req, timeout=20):
            return _FakeHTTPResponse(
                status=200,
                body=b'{"status":"ok"}',
                headers={"Access-Control-Allow-Origin": "https://console.svc.plus"},
            )

        res = probe.probe_https_mirror(
            domain="cn-dl.svc.plus",
            key_path="releases/_health/probe.json",
            origin="https://console.svc.plus",
            opener=ok_opener,
        )
        self.assertTrue(res["ok"])

        sig = verify_txt.sign_aliyun_rpc_params(
            {"Action": "DescribeVerifyContent", "DomainName": "cn-dl.svc.plus"}, "secret"
        )
        self.assertIn("Signature=", sig)

    def test_shell_scripts_pass_bash_syntax_check(self):
        scripts = sorted((CLIENT_MIRRORS_ROOT / "scripts").glob("*.sh"))
        self.assertGreaterEqual(len(scripts), 4)
        for script in scripts:
            proc = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0, f"{script.name}: {proc.stderr}")


if __name__ == "__main__":
    unittest.main()
