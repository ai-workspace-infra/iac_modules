import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate  # noqa: E402


class GenerateTest(unittest.TestCase):
    def test_firewall_label_is_stable_and_within_linode_limit(self):
        label = "open-platform-uat-ak-open-platform"
        rendered = generate.firewall_label(label)

        self.assertLessEqual(len(rendered), generate.LINODE_FIREWALL_LABEL_MAX)
        self.assertEqual(rendered, generate.firewall_label(label))
        self.assertNotEqual(rendered, label + "-firewall")

    def test_render_expands_explicit_linode_blocks(self):
        fixture = ROOT / "tests" / "fixtures" / "linode.yaml"
        with tempfile.TemporaryDirectory() as tempdir:
            workdir = Path(tempdir)
            generate.render(SimpleNamespace(resources=fixture, workdir=workdir))

            content = (workdir / "generated_hosts.tf").read_text(encoding="utf-8")
            self.assertIn('resource "linode_sshkey" "test_admin"', content)
            self.assertIn('resource "linode_firewall" "fw_web_node"', content)
            self.assertIn('module "compute_web_node"', content)
            self.assertIn('ip          = module.compute_web_node.main_ip', content)
            self.assertNotRegex(content, r"\b(for_each|count|dynamic)\b")

            tfvars = json.loads((workdir / "terraform.auto.tfvars.json").read_text())
            self.assertEqual(tfvars["region"], "us-east")
            self.assertEqual(tfvars["type"], "g6-nanode-1")

            manifest = json.loads((workdir / "hosts_manifest.json").read_text())
            self.assertEqual(manifest["provider"], "akamai-cloud")
            self.assertEqual(manifest["hosts"][0]["label"], "test-web-node")

    def test_inventory_preserves_groups_and_ssh_user_in_cmdb(self):
        fixture = ROOT / "tests" / "fixtures" / "linode.yaml"
        with tempfile.TemporaryDirectory() as tempdir:
            workdir = Path(tempdir)
            generate.render(SimpleNamespace(resources=fixture, workdir=workdir))
            with mock.patch.object(
                generate,
                "terraform_output",
                return_value={
                    "web-node": {
                        "ip": "198.51.100.10",
                        "private_ip": "10.0.0.10",
                        "ipv6": "2001:db8::10/128",
                        "instance_id": 123,
                    }
                },
            ):
                generate.inventory(SimpleNamespace(resources=fixture, workdir=workdir))

            cmdb = json.loads((workdir / "cmdb.json").read_text())
            self.assertEqual(cmdb["web.example.test"]["groups"], ["web", "debian"])
            self.assertEqual(cmdb["web.example.test"]["ansible_user"], "root")


if __name__ == "__main__":
    unittest.main()
