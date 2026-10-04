import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate.py"
SPEC = importlib.util.spec_from_file_location("gcp_generate", SCRIPT)
generator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(generator)


def manifest(mode, cidrs):
    return {
        "kind": "GCPWorkloadNamespace",
        "metadata": {"name": "vault-shared", "environment": "shared", "provider": "gcp"},
        "spec": {
            "gcp_account_id": "open-platform-prod",
            "project_id": "open-platform-prod",
            "organization_id": "744119519286",
            "region": "asia-east1",
            "workspace": "vault-shared",
            "state_namespace": "vault-shared",
            "network_name": "vault-shared",
            "subnet_cidr": "10.81.0.0/20",
            "state": {"key": "terraform/shared/open-platform-prod/gcp-cloud/open-platform-prod/vault-shared/terraform.tfstate"},
            "enable_iap_ssh": False,
            "enable_oslogin": True,
            "ssh_access_mode": mode,
            "ssh_source_ranges": cidrs,
            "resources": {"vault_nodes": [{"name": "vault-prod-0", "zone": "asia-east1-a", "machine_type": "e2-highcpu-2", "xconnect_role": "gateway", "public_ip": True}, {"name": "vault-prod-1", "zone": "asia-east1-b", "machine_type": "e2-highcpu-2", "xconnect_role": "one", "public_ip": True}]},
        },
    }


class VaultSshCutoverTests(unittest.TestCase):
    def test_public_bootstrap_requires_allowlisted_source(self):
        generator.normalize_resources(manifest("bootstrap-public", ["35.79.83.48/32"]))
        with self.assertRaises(SystemExit):
            generator.normalize_resources(manifest("bootstrap-public", []))

    def test_zero_trust_removes_public_ssh(self):
        generator.normalize_resources(manifest("xconnect-zero", []))
        with self.assertRaises(SystemExit):
            generator.normalize_resources(manifest("xconnect-zero", ["35.79.83.48/32"]))


if __name__ == "__main__":
    unittest.main()
