import unittest
import importlib.util
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class SpotVMDeploymentContractTest(unittest.TestCase):
    def test_public_vault_node_inventory_uses_terraform_address(self):
        spec = importlib.util.spec_from_file_location("gcp_generate", ROOT / "scripts" / "generate.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        manifest = {
            "global": {"environment": "shared", "project_id": "open-platform-shared", "ssh_username": "ubuntu"},
            "vault_nodes": [{"name": "vault-shared-0", "zone": "asia-east1-a", "public_ip": True}],
        }
        runtime = {
            "project_id": "open-platform-shared",
            "vault_private_ips": {"vault-shared-0": "10.82.0.2"},
            "vault_public_ips": {"vault-shared-0": "198.51.100.20"},
        }
        with tempfile.TemporaryDirectory() as tempdir, patch.object(
            generator, "load_resources", return_value=manifest
        ), patch.object(generator.subprocess, "check_output", return_value=json.dumps(runtime)):
            generator.inventory(SimpleNamespace(resources="ignored", workdir=tempdir))
            cmdb = json.loads((Path(tempdir) / "cmdb.json").read_text(encoding="utf-8"))
            inventory = (Path(tempdir) / "inventory.ini").read_text(encoding="utf-8")
        self.assertEqual(cmdb["vault_nodes"][0]["public_ip"], "198.51.100.20")
        self.assertIn("vault-shared-0 ansible_host=198.51.100.20 ansible_user=ubuntu", inventory)

    def test_namespace_public_ip_allowlist_renders_project_org_policy(self):
        spec = importlib.util.spec_from_file_location("gcp_generate", ROOT / "scripts" / "generate.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        manifest = {
            "kind": "GCPWorkloadNamespace",
            "metadata": {"name": "shared-vault", "environment": "shared", "provider": "gcp"},
            "spec": {
                "gcp_account_id": "open-platform-shared", "project_id": "open-platform-shared",
                "organization_id": "744119519286", "region": "asia-east1",
                "workspace": "shared-vault", "state_namespace": "shared-vault",
                "state": {"key": "terraform/shared/open-platform-shared/gcp-cloud/open-platform-shared/shared-vault/terraform.tfstate"},
                "network_name": "shared-vault", "subnet_cidr": "10.82.0.0/20",
                "ssh_access_mode": "bootstrap-public", "ssh_source_ranges": ["203.0.113.10/32"],
                "external_ip_allowed_instances": [
                    {"name": "vault-shared-0", "zone": "asia-east1-a"},
                    {"name": "observability-shared-0", "zone": "asia-east1-a"},
                    {"name": "iam-shared-0", "zone": "asia-east1-a"},
                ],
                "resources": {"vault_nodes": [{
                    "name": "vault-shared-0", "zone": "asia-east1-a",
                    "machine_type": "e2-highcpu-2", "xconnect_role": "gateway", "public_ip": True,
                }]},
            },
        }
        with tempfile.TemporaryDirectory() as tempdir, patch.object(generator, "load_resources", return_value=manifest):
            generator.render(SimpleNamespace(resources="ignored", workdir=tempdir))
            rendered = (Path(tempdir) / "generated_platform.tf").read_text(encoding="utf-8")
        self.assertIn('resource "google_org_policy_policy" "vm_external_ip_access"', rendered)
        self.assertIn('name   = "projects/${module.project.project_number}/policies/compute.vmExternalIpAccess"', rendered)
        self.assertIn('parent = "projects/${module.project.project_number}"', rendered)
        for name in ("vault-shared-0", "observability-shared-0", "iam-shared-0"):
            self.assertIn(f"instances/{name}", rendered)
        self.assertIn("google_org_policy_policy.vm_external_ip_access", rendered)

    def test_member_only_namespace_is_supported_without_gateway(self):
        spec = importlib.util.spec_from_file_location("gcp_generate", ROOT / "scripts" / "generate.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        manifest = {
            "kind": "GCPWorkloadNamespace",
            "metadata": {"name": "shared-observability", "environment": "shared", "provider": "gcp"},
            "spec": {
                "gcp_account_id": "open-platform-shared", "project_id": "open-platform-shared",
                "organization_id": "744119519286", "region": "asia-east1",
                "workspace": "shared-observability", "state_namespace": "shared-observability",
                "network_name": "shared-observability", "subnet_cidr": "10.83.0.0/20",
                "xconnect_mode": "member", "ssh_access_mode": "bootstrap-public",
                "ssh_source_ranges": ["203.0.113.10/32"],
                "state": {"key": "terraform/shared/open-platform-shared/gcp-cloud/open-platform-shared/shared-observability/terraform.tfstate"},
                "resources": {"vault_nodes": [{
                    "name": "observability-shared-0", "zone": "asia-east1-a",
                    "machine_type": "e2-medium", "xconnect_role": "one", "public_ip": True,
                }]},
            },
        }
        _, nodes, _, _, _ = generator.normalize_resources(manifest)
        self.assertEqual(nodes[0]["xconnect_role"], "one")

    def test_public_spot_vm_has_configurable_ssh_and_no_forced_hourly_expiry(self):
        module = (ROOT / "modules" / "spot_vm" / "main.tf").read_text(encoding="utf-8")
        template = (ROOT / "templates" / "open-platform.tf.j2").read_text(encoding="utf-8")
        generator = (ROOT / "scripts" / "generate.py").read_text(encoding="utf-8")

        self.assertIn('default     = null', module)
        self.assertIn('var.max_run_duration_seconds == null ? true :', module)
        self.assertIn('instance_termination_action = "STOP"', module)
        self.assertIn('for_each = var.max_run_duration_seconds == null ? []', module)
        self.assertIn('condition     = !var.public_ip || trimspace(var.ssh_public_key) != ""', module)
        self.assertIn('public_ip       = {{ vm.public_ip | default(false) | tojson }}', template)
        self.assertIn('source_ranges = {{ spot_ssh_source_ranges | tojson }}', template)
        self.assertIn('ssh_public_key  = var.ssh_public_key', template)
        self.assertIn('"groups": vm.get("inventory_groups", [])', generator)
        self.assertIn('network_tags    = {{ vm.network_tags | default([]) | tojson }}', template)
        self.assertIn('"ip": address', generator)
        self.assertNotIn('"spot_ssh_source_ranges",', generator.split('declared = {', 1)[1].split('}', 1)[0])

    def test_public_spot_instance_reaches_deploy_matrix(self):
        spec = importlib.util.spec_from_file_location("gcp_generate", ROOT / "scripts" / "generate.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        manifest = {
            "kind": "GCPWorkloadNamespace",
            "metadata": {"name": "sample", "environment": "uat", "provider": "gcp"},
            "spec": {
                "gcp_account_id": "test-account", "project_id": "test-project",
                "organization_id": "123", "region": "asia-east1", "workspace": "sample",
                "state_namespace": "sample", "network_name": "sample-net",
                "state": {"key": "terraform/uat/test-project/gcp-cloud/test-account/sample/terraform.tfstate"},
                "subnet_cidr": "10.40.0.0/24", "spot_ssh_source_ranges": ["203.0.113.10/32"],
                "spot_network_tags": ["sample-ssh"], "ssh_username": "deployer",
                "resources": {"spot_vms": [{
                    "name": "sample-vm", "zone": "asia-east1-a", "machine_type": "e2-custom-4-8192",
                    "public_ip": True, "network_tags": ["sample-ssh"],
                    "inventory_groups": ["ai_workspace"],
                }]},
            },
        }
        runtime = {
            "project_id": "test-project", "spot_instances": {"sample-vm": {
                "public_ip": "198.51.100.10", "provisioning_model": "SPOT",
            }},
        }
        with tempfile.TemporaryDirectory() as tempdir, patch.object(
            generator, "load_resources", return_value=manifest
        ), patch.object(generator.subprocess, "check_output", return_value=json.dumps(runtime)):
            generator.inventory(SimpleNamespace(resources="ignored", workdir=tempdir))
            cmdb = json.loads((Path(tempdir) / "cmdb.json").read_text(encoding="utf-8"))
            inventory = (Path(tempdir) / "inventory.ini").read_text(encoding="utf-8")
        self.assertEqual(cmdb["sample-vm"]["ip"], "198.51.100.10")
        self.assertEqual(cmdb["sample-vm"]["groups"], ["ai_workspace"])
        self.assertIn("sample-vm ansible_host=198.51.100.10 ansible_user=deployer", inventory)


if __name__ == "__main__":
    unittest.main()
