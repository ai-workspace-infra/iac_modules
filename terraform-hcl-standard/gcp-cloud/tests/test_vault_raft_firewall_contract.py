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

    def test_iap_ssh_is_explicitly_opt_in_and_scoped(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        generator = GENERATOR.read_text(encoding="utf-8")
        module = (ROOT / "modules" / "vault_vm" / "main.tf").read_text(encoding="utf-8")
        fixture = (ROOT / "tests" / "fixtures" / "iap-enabled-vault.yaml").read_text(encoding="utf-8")

        self.assertIn('"enable_iap_ssh": spec.get("enable_iap_ssh", False)', generator)
        self.assertIn('if not isinstance(global_config["enable_iap_ssh"], bool)', generator)
        self.assertIn("{% if vault_nodes and enable_iap_ssh %}", template)
        self.assertIn('source_ranges = ["35.235.240.0/20"]', template)
        self.assertIn('role       = "roles/iap.tunnelResourceAccessor"', template)
        self.assertIn('role          = "roles/compute.osAdminLogin"', template)
        self.assertIn('role    = "roles/compute.viewer"', template)
        self.assertIn('"enable-oslogin" = "TRUE"', module)
        self.assertIn('role               = "roles/iam.serviceAccountUser"', module)
        self.assertIn("enable_iap_ssh: true", fixture)
        self.assertIn("ssh_source_ranges: []", fixture)

    def test_direct_ssh_key_is_instance_scoped_and_disabled_with_oslogin(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        module = (ROOT / "modules" / "vault_vm" / "main.tf").read_text(encoding="utf-8")
        variables = (ROOT / "templates" / "variables.tf").read_text(encoding="utf-8")

        self.assertIn("ssh_public_key = var.ssh_public_key", template)
        self.assertIn("ssh_username   = var.ssh_username", template)
        self.assertIn('"ssh-keys" = "${var.ssh_username}:${trimspace(var.ssh_public_key)}"', module)
        self.assertIn('!var.enable_oslogin && trimspace(var.ssh_public_key) != ""', module)
        self.assertIn('default     = "github-actions"', module)
        self.assertIn('variable "ssh_public_key"', variables)
        self.assertIn('variable "ssh_username"', variables)


if __name__ == "__main__":
    unittest.main()
