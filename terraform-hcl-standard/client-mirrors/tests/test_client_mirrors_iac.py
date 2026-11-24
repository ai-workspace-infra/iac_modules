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
REPOS_FIXTURE = TESTS_DIR / "fixtures" / "repos.yaml"

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
        self.assertIn('oss_policy_prefixes  = ["releases/*", "offline-package/*"]', generated)
        self.assertEqual(generate.check_hcl_tree(workdir), [])

        summary = json.loads((workdir / "rendered_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["stack"], "mirrors")
        self.assertEqual(summary["probe_path"], "releases/_health/probe.json")
        self.assertEqual(summary["aliyun_oss_cdn"]["oss_policy_prefixes"], ["releases/*", "offline-package/*"])
        self.assertEqual(summary["aliyun_oss_cdn"]["cdn_tls_vault_path"], "")

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

    def test_render_repos_stack_with_manifest_and_custom_fields(self):
        workdir = self.tmp / "repos-workdir"
        rc = generate.main(["render", "--manifest", str(REPOS_FIXTURE), "--workdir", str(workdir)])
        self.assertEqual(rc, 0)

        generated = (workdir / "generated_mirrors.tf").read_text(encoding="utf-8")
        self.assertIn('bucket_name          = "svc-plus-repos-global"', generated)
        self.assertIn('custom_domain        = "repo.svc.plus"', generated)
        self.assertIn('bucket_name          = "svc-plus-repos-cn-hk"', generated)
        self.assertIn('cdn_domain           = "cn-repo.svc.plus"', generated)
        self.assertIn('oss_policy_prefixes  = ["apt/*", "yum/*", "apk/*", "_health/*"]', generated)
        self.assertIn('cdn_tls_vault_path  = "CICD/domains/svc.plus"', generated)
        self.assertIn('probe_path = "_health/probe.json"', generated)
        self.assertEqual(generate.check_hcl_tree(workdir), [])

        summary = json.loads((workdir / "rendered_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["stack"], "repos")
        self.assertEqual(summary["namespace"], "repos")
        self.assertEqual(summary["probe_path"], "_health/probe.json")
        self.assertEqual(summary["state_key"], "terraform/prod/svc.plus/client-mirrors/svc-plus-prod/repos/terraform.tfstate")
        self.assertEqual(summary["cloudflare_r2"]["custom_domain"], "repo.svc.plus")
        self.assertEqual(summary["aliyun_oss_cdn"]["cdn_domain"], "cn-repo.svc.plus")
        self.assertEqual(summary["aliyun_oss_cdn"]["cdn_tls_vault_path"], "CICD/domains/svc.plus")
        self.assertEqual(summary["aliyun_oss_cdn"]["oss_policy_prefixes"], ["apt/*", "yum/*", "apk/*", "_health/*"])

        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc2 = generate.main(["state-key", "--manifest", str(REPOS_FIXTURE)])
        self.assertEqual(rc2, 0)
        self.assertEqual(
            buf.getvalue().strip(),
            "terraform/prod/svc.plus/client-mirrors/svc-plus-prod/repos/terraform.tfstate",
        )

    def test_stack_flag_resolves_gitops_manifest_and_default_workdir(self):
        fake_root = self.tmp / "workspace"
        gitops_dir = fake_root / "gitops" / "resources" / "svc.plus" / "prod" / "client-mirrors"
        gitops_dir.mkdir(parents=True)
        shutil.copyfile(FIXTURE, gitops_dir / "mirrors.yaml")
        shutil.copyfile(REPOS_FIXTURE, gitops_dir / "repos.yaml")

        resolved_mirrors = generate.resolve_manifest_path(stack="mirrors", search_roots=(fake_root,))
        resolved_repos = generate.resolve_manifest_path(stack="repos", search_roots=(fake_root,))
        self.assertEqual(resolved_mirrors, gitops_dir / "mirrors.yaml")
        self.assertEqual(resolved_repos, gitops_dir / "repos.yaml")

        self.assertEqual(generate.default_workdir_for_stack("mirrors"), CLIENT_MIRRORS_ROOT / "envs" / "svc-plus-prod")
        self.assertEqual(generate.default_workdir_for_stack("repos"), CLIENT_MIRRORS_ROOT / "envs" / "svc-plus-prod-repos")

        repos_workdir = self.tmp / "envs-repos"
        with mock.patch.object(generate, "resolve_manifest_path", return_value=gitops_dir / "repos.yaml"):
            rc = generate.main(["render", "--stack", "repos", "--workdir", str(repos_workdir)])
        self.assertEqual(rc, 0)
        summary = json.loads((repos_workdir / "rendered_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["stack"], "repos")

    def test_manifest_validation_for_stack_prefixes_and_probe_path(self):
        with self.assertRaises(ValueError):
            generate.load_and_validate_manifest(FIXTURE, stack="repos")

        bad_prefix_yaml = REPOS_FIXTURE.read_text(encoding="utf-8").replace("- apt/*", "- /apt/*")
        bad_prefix_path = self.tmp / "bad-prefix.yaml"
        bad_prefix_path.write_text(bad_prefix_yaml, encoding="utf-8")
        with self.assertRaises(ValueError):
            generate.load_and_validate_manifest(bad_prefix_path)

        bad_wildcard_yaml = REPOS_FIXTURE.read_text(encoding="utf-8").replace("- apt/*", "- '*'")
        bad_wildcard_path = self.tmp / "bad-wildcard.yaml"
        bad_wildcard_path.write_text(bad_wildcard_yaml, encoding="utf-8")
        with self.assertRaises(ValueError):
            generate.load_and_validate_manifest(bad_wildcard_path)

        bad_probe_yaml = REPOS_FIXTURE.read_text(encoding="utf-8").replace(
            "probe_path: _health/probe.json", "probe_path: ../secret.json"
        )
        bad_probe_path = self.tmp / "bad-probe.yaml"
        bad_probe_path.write_text(bad_probe_yaml, encoding="utf-8")
        with self.assertRaises(ValueError):
            generate.load_and_validate_manifest(bad_probe_path)

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
