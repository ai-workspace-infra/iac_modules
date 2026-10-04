"""A public Spot VM that serves traffic (for example a regional Agent Proxy).

The deploy pipeline keys such a node by its first service domain, needs its
inventory variables, and must be able to reach its service ports; a VM that
declares none of this keeps the plain entry it always had.
"""
import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_generator():
    spec = importlib.util.spec_from_file_location("gcp_generate", ROOT / "scripts" / "generate.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    return generator


def manifest(**vm_overrides):
    vm = {
        "name": "agent-proxy-us-uat", "zone": "us-central1-a", "machine_type": "e2-custom-2-2048",
        "enable_oslogin": True, "public_ip": True, "network_tags": ["agent-proxy-us"],
        "public_tcp_ports": [80, 443],
        "inventory_groups": ["xconnect", "agent_proxy", "uat", "gcp_cloud"],
        "tags": ["svc-plus", "uat"], "location": "us", "node_label": "agent-proxy-us",
        "host_vars": {
            "role": "xconnect", "logical_region": "us-ca", "provider_region": "us-central1",
            "service_domains": ["us-xconnect.svc.plus"],
        },
    }
    vm.update(vm_overrides)
    for key in [key for key, value in vm.items() if value is None]:
        del vm[key]
    return {
        "kind": "GCPWorkloadNamespace",
        "metadata": {"name": "agent-proxy-us", "environment": "uat", "provider": "gcp"},
        "spec": {
            "gcp_account_id": "test-account", "project_id": "test-project", "organization_id": "123",
            "region": "us-central1", "workspace": "agent-proxy-us", "state_namespace": "agent-proxy-us",
            "network_name": "agent-proxy-us-uat-gcp", "subnet_cidr": "10.66.0.0/24",
            "state": {"key": "terraform/uat/test-project/gcp-cloud/test-account/agent-proxy-us/terraform.tfstate"},
            "spot_ssh_source_ranges": ["0.0.0.0/0"], "spot_network_tags": ["agent-proxy-us"],
            "resources": {"spot_vms": [vm]},
        },
    }


RUNTIME = {
    "project_id": "test-project",
    "spot_instances": {"agent-proxy-us-uat": {
        "public_ip": "198.51.100.30", "private_ip": "10.66.0.8", "zone": "us-central1-a",
        "provisioning_model": "SPOT",
    }},
}


class SpotPublicServiceNodeTest(unittest.TestCase):
    def setUp(self):
        self.generator = load_generator()

    def render(self, document):
        def fake_run(command, **kwargs):
            self.assertEqual(command[:2], ["terraform", "fmt"])
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tempdir, patch.object(
            self.generator, "load_resources", return_value=copy.deepcopy(document)
        ), patch.object(self.generator.subprocess, "run", side_effect=fake_run):
            self.generator.render(SimpleNamespace(resources="ignored", workdir=tempdir))
            return (Path(tempdir) / "generated_platform.tf").read_text(encoding="utf-8")

    def inventory(self, document):
        with tempfile.TemporaryDirectory() as tempdir, patch.object(
            self.generator, "load_resources", return_value=copy.deepcopy(document)
        ), patch.object(
            self.generator.subprocess, "check_output", return_value=json.dumps(RUNTIME)
        ), patch.dict(os.environ, {"GCP_OSLOGIN_USERNAME": "sa_123"}):
            self.generator.inventory(SimpleNamespace(resources="ignored", workdir=tempdir))
            return (
                json.loads((Path(tempdir) / "cmdb.json").read_text(encoding="utf-8")),
                (Path(tempdir) / "inventory.ini").read_text(encoding="utf-8"),
            )

    def test_service_ports_get_their_own_firewall_rule(self):
        rendered = self.render(manifest())
        rule = rendered.split('resource "google_compute_firewall" "spot_public_tcp_agent_proxy_us_uat"', 1)[1]
        rule = rule.split("\nresource ", 1)[0]
        self.assertIn('name          = "agent-proxy-us-uat-public-tcp"', rule)
        self.assertIn('source_ranges = ["0.0.0.0/0"]', rule)
        self.assertIn('target_tags   = ["agent-proxy-us"]', rule)
        self.assertIn('ports    = ["80", "443"]', rule)
        # SSH is still only the dedicated rule.
        ssh_rule = rendered.split('resource "google_compute_firewall" "spot_ssh"', 1)[1]
        self.assertIn('ports    = ["22"]', ssh_rule)
        self.assertNotIn('"22"', rule)

    def test_vm_without_service_ports_renders_no_extra_rule(self):
        rendered = self.render(manifest(public_tcp_ports=None))
        self.assertNotIn("spot_public_tcp_", rendered)

    def test_service_node_is_keyed_by_its_first_service_domain(self):
        cmdb, inventory = self.inventory(manifest())
        self.assertNotIn("agent-proxy-us-uat", cmdb)
        node = cmdb["us-xconnect.svc.plus"]
        self.assertEqual(node["name"], "agent-proxy-us-uat")
        self.assertEqual(node["ip"], "198.51.100.30")
        self.assertIs(node["iap_tunnel"], False)
        self.assertEqual(node["groups"], ["xconnect", "agent_proxy", "uat", "gcp_cloud"])
        self.assertEqual(node["host_vars"]["logical_region"], "us-ca")
        self.assertEqual(node["host_vars"]["node_id"], "agent-proxy-us-uat")
        self.assertEqual(node["host_vars"]["location"], "us")
        self.assertEqual(cmdb["declared_spot_vms"], ["agent-proxy-us-uat"])
        line = next(line for line in inventory.splitlines() if line.startswith("us-xconnect.svc.plus "))
        self.assertTrue(line.startswith("us-xconnect.svc.plus ansible_host=198.51.100.30 ansible_user=sa_123 "))
        self.assertIn('logical_region="us-ca"', line)
        self.assertIn("service_domains=\"['us-xconnect.svc.plus']\"", line)
        self.assertIn("[agent_proxy]\nus-xconnect.svc.plus ", inventory)

    def test_plain_spot_vm_entry_is_unchanged(self):
        plain = manifest(host_vars=None, public_tcp_ports=None, tags=None, location=None, node_label=None,
                         inventory_groups=["ai_workspace"])
        cmdb, inventory = self.inventory(plain)
        node = cmdb["agent-proxy-us-uat"]
        self.assertEqual(node["host_vars"], {})
        for key, value in {
            "ip": "198.51.100.30", "private_ip": "10.66.0.8", "public_ip": "198.51.100.30",
            "zone": "us-central1-a", "ansible_user": "sa_123", "groups": ["ai_workspace"],
            "provider": "gcp-cloud", "provisioning_model": "SPOT", "iap_tunnel": False,
        }.items():
            self.assertEqual(node[key], value, key)
        self.assertIn("[ai_workspace]\nagent-proxy-us-uat ansible_host=198.51.100.30 ansible_user=sa_123\n", inventory)

    def test_invalid_service_declarations_are_rejected(self):
        cases = {
            "ssh port": {"public_tcp_ports": [22, 443]},
            "not a port": {"public_tcp_ports": [70000]},
            "boolean port": {"public_tcp_ports": [True]},
            "duplicate port": {"public_tcp_ports": [443, 443]},
            "ports on a private vm": {"public_ip": False},
            "ports without a firewall target": {"network_tags": []},
            "service domain that is not a DNS name": {"host_vars": {"service_domains": ["us xconnect"]}},
            "host var that would break the inventory line": {"host_vars": {"role": 'x" ansible_user="root'}},
            "host var name": {"host_vars": {"bad name": "x"}},
        }
        for label, override in cases.items():
            with self.subTest(label):
                with self.assertRaises(SystemExit):
                    self.generator.normalize_resources(manifest(**override))

    def test_service_domains_on_a_private_vm_are_rejected(self):
        document = manifest(public_ip=False, public_tcp_ports=None)
        document["spec"]["enable_iap_ssh"] = True
        with self.assertRaises(SystemExit) as raised:
            self.generator.normalize_resources(document)
        self.assertIn("requires public_ip: true", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
