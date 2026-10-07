import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "xconnect-lab-contract.py"
SPEC = importlib.util.spec_from_file_location("xconnect_lab_prepare", SCRIPT)
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class XConnectLabPrepareTests(unittest.TestCase):
    def declaration(self, folder: Path, provider="aws-spot") -> Path:
        path = folder / "declaration.json"
        path.write_text(json.dumps({"spec": {
            "gateway_provider": provider,
            "ttl_minutes": 60,
            "aws": {"region": "ap-northeast-1", "ami_ssm_parameter": "/aws/service/ami"},
            "nodes": {
                "one": {"instance_type": "t4g.micro"},
                "gateway": {"instance_type": "t4g.small"},
            },
            "zero": {
                "accounts_api_url": "https://accounts-uat.onwalk.net",
                "portal_url": "https://console-serverless-uat.onwalk.net/panel/xconnect-zero",
            },
            "gateway_transport": {
                "enabled": True,
                "port": 443,
                "transport": "vless-xhttp",
                "public_wireguard_ingress": False,
            },
        }}), encoding="utf-8")
        return path

    def test_backend_is_exact_run_scoped_private_and_contains_no_output_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            environment = {
                "TF_VAR_run_id": "xcl-123-4",
                "TF_STATE_BUCKET": "state-bucket",
                "TF_STATE_REGION": "auto",
                "TF_STATE_ENDPOINT": "https://state.invalid",
                "TF_STATE_ACCESS_KEY": "runtime-access",
                "TF_STATE_SECRET_KEY": "runtime-secret",
            }
            CONTRACT.render("backend", folder, self.declaration(folder), environment)
            backend_path = folder / "backend.json"
            backend = json.loads(backend_path.read_text(encoding="utf-8"))
            self.assertEqual(
                backend["key"],
                "terraform/uat/svc.plus/aws-cloud/primary/xconnect-lab/xcl-123-4/terraform.tfstate",
            )
            self.assertEqual(stat.S_IMODE(backend_path.stat().st_mode), 0o600)

    def test_resources_bind_ami_runner_and_ephemeral_ingress(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "id_ed25519.pub").write_text("ssh-ed25519 test", encoding="utf-8")
            environment = {
                "TF_VAR_run_id": "xcl-123-4",
                "GATEWAY_PROVIDER": "aws-spot",
                "LAB_VLESS_ID": "12345678-1234-4234-8234-123456789abc",
                "ZERO_SERVICE_TOKEN": "x" * 32,
                "ZERO_OWNER_EMAIL": "owner@example.invalid",
                "GATEWAY_TRANSPORT_INGRESS_CIDRS": "198.51.100.10/32",
                "SSH_DEBUG_INGRESS_CIDRS": "192.0.2.20/32",
            }
            calls = ["ami-123", json.dumps({"Images": [{
                "Architecture": "arm64", "OwnerId": "099720109477",
            }]})]
            with patch.object(CONTRACT.subprocess, "check_output", side_effect=calls), patch.object(
                CONTRACT.urllib.request, "urlopen", return_value=Response(b"203.0.113.9\n")
            ):
                CONTRACT.render("resources", folder, self.declaration(folder), environment)
            variables_path = folder / "variables.json"
            variables = json.loads(variables_path.read_text(encoding="utf-8"))
            self.assertEqual(variables["aws_ami"], "ami-123")
            self.assertEqual(variables["runner_cidr"], "203.0.113.9/32")
            self.assertEqual(variables["gateway_transport_ingress_cidrs"], ["198.51.100.10/32"])
            self.assertEqual(variables["ssh_debug_ingress_cidrs"], ["192.0.2.20/32"])
            self.assertEqual(stat.S_IMODE(variables_path.stat().st_mode), 0o600)
            self.assertNotIn(environment["ZERO_SERVICE_TOKEN"], variables_path.read_text(encoding="utf-8"))

    def test_resources_reject_unreviewed_ami_and_broad_ingress(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "id_ed25519.pub").write_text("ssh-ed25519 test", encoding="utf-8")
            environment = {
                "TF_VAR_run_id": "xcl-123-4",
                "GATEWAY_PROVIDER": "aws-spot",
                "LAB_VLESS_ID": "12345678-1234-4234-8234-123456789abc",
                "ZERO_SERVICE_TOKEN": "x" * 32,
                "ZERO_OWNER_EMAIL": "owner@example.invalid",
                "GATEWAY_TRANSPORT_INGRESS_CIDRS": "0.0.0.0/0",
            }
            with self.assertRaises(ValueError):
                CONTRACT.render("resources", folder, self.declaration(folder), environment)
            environment["GATEWAY_TRANSPORT_INGRESS_CIDRS"] = ""
            calls = ["ami-foreign", json.dumps({"Images": [{
                "Architecture": "amd64", "OwnerId": "000000000000",
            }]})]
            with patch.object(CONTRACT.subprocess, "check_output", side_effect=calls):
                with self.assertRaises(ValueError):
                    CONTRACT.render("resources", folder, self.declaration(folder), environment)


if __name__ == "__main__":
    unittest.main()
