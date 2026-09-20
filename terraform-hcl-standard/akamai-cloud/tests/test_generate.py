import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate  # noqa: E402


class GenerateTest(unittest.TestCase):
    def test_render_expands_explicit_linode_blocks(self):
        fixture = ROOT / "tests" / "fixtures" / "linode.yaml"
        with tempfile.TemporaryDirectory() as tempdir:
            workdir = Path(tempdir)
            generate.render(SimpleNamespace(resources=fixture, workdir=workdir))

            content = (workdir / "generated_hosts.tf").read_text(encoding="utf-8")
            self.assertIn('resource "linode_sshkey" "test_admin"', content)
            self.assertIn('resource "linode_firewall" "fw_web_node"', content)
            self.assertIn('module "compute_web_node"', content)
            self.assertIn('source = "../../modules/compute"', content)
            self.assertNotRegex(content, r"\b(for_each|count|dynamic)\b")

            tfvars = json.loads((workdir / "terraform.auto.tfvars.json").read_text())
            self.assertEqual(tfvars["region"], "us-east")
            self.assertEqual(tfvars["type"], "g6-nanode-1")

            manifest = json.loads((workdir / "hosts_manifest.json").read_text())
            self.assertEqual(manifest["provider"], "akamai-cloud")
            self.assertEqual(manifest["hosts"][0]["label"], "test-web-node")

    def test_prod_render_enables_terraform_delete_protection(self):
        fixture = ROOT / "tests" / "fixtures" / "linode-prod.yaml"
        with tempfile.TemporaryDirectory() as tempdir:
            workdir = Path(tempdir)
            generate.render(SimpleNamespace(resources=fixture, workdir=workdir))

            content = (workdir / "generated_hosts.tf").read_text(encoding="utf-8")
            self.assertIn('source = "../../modules/compute_protected"', content)


if __name__ == "__main__":
    unittest.main()
