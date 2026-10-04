"""Gateway-tagged private service ports stay private in a shared Spot renderer."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gcp_generate", ROOT / "scripts" / "generate.py")
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


def declaration():
    return {
        "global": {
            "environment": "uat", "project_id": "test-project", "region": "asia-east1",
            "network_name": "test-private", "subnet_cidr": "10.86.0.0/24",
            "enable_iap_ssh": True, "spot_network_tags": ["test-ssh"],
        },
        "spot_vms": [
            {"name": "gateway-01", "zone": "asia-east1-a", "machine_type": "e2-medium",
             "public_ip": False, "network_tags": ["gateway", "test-ssh"]},
            {"name": "cpa-01", "zone": "asia-east1-a", "machine_type": "e2-medium",
             "public_ip": False, "network_tags": ["cpa-01", "test-ssh"],
             "private_tcp_ports": [8317], "private_source_tags": ["gateway"],
             "private_target_tags": ["cpa-01"]},
        ],
    }


class SpotPrivateServicePortsTest(unittest.TestCase):
    def test_private_port_is_limited_to_gateway_tag(self):
        with tempfile.TemporaryDirectory() as workdir, patch.object(
            GENERATOR, "load_resources", return_value=declaration()
        ), patch.object(GENERATOR.subprocess, "run"):
            GENERATOR.render(SimpleNamespace(resources="unused", workdir=workdir))
            rendered = (Path(workdir) / "generated_platform.tf").read_text()
        rule = rendered.split('resource "google_compute_firewall" "spot_private_tcp_cpa_01"', 1)[1]
        rule = rule.split("\nresource ", 1)[0]
        self.assertIn('source_tags = ["gateway"]', rule)
        self.assertIn('target_tags = ["cpa-01"]', rule)
        self.assertIn('ports    = ["8317"]', rule)
        self.assertNotIn("0.0.0.0/0", rule)
        self.assertNotIn("spot_public_tcp_cpa_01", rendered)

    def test_port_without_source_tag_is_rejected(self):
        vm = declaration()["spot_vms"][1]
        vm["private_source_tags"] = []
        with self.assertRaisesRegex(SystemExit, "require source tags"):
            GENERATOR.validate_spot_service_declaration(vm)

    def test_ssh_and_duplicate_private_ports_are_rejected(self):
        vm = declaration()["spot_vms"][1]
        for ports in ([22], [8317, 8317]):
            with self.subTest(ports=ports), self.assertRaisesRegex(SystemExit, "unique non-SSH"):
                GENERATOR.validate_spot_service_declaration({**vm, "private_tcp_ports": ports})


if __name__ == "__main__":
    unittest.main()
