import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "open-platform.tf.j2"
GENERATOR = ROOT / "scripts" / "generate.py"


class VaultRaftFirewallContractTest(unittest.TestCase):
    def test_raft_ports_are_limited_to_declared_subnet(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('{% if vault_nodes %}\nresource "google_compute_firewall" "vault_raft_internal"', template)
        self.assertIn('source_ranges = [{{ subnet_cidr | tojson }}]', template)
        self.assertIn('target_tags   = ["vault"]', template)
        self.assertIn('ports    = ["8200", "8201"]', template)
        self.assertNotIn('source_ranges = ["0.0.0.0/0"]\n  target_tags   = ["vault"]', template)

    def test_renderer_passes_manifest_subnet_into_template(self):
        generator = GENERATOR.read_text(encoding="utf-8")
        self.assertIn('subnet_cidr=global_config.get("subnet_cidr", "")', generator)


if __name__ == "__main__":
    unittest.main()
