import unittest
import importlib.util
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class SpotVMDeploymentContractTest(unittest.TestCase):
    def test_org_policy_api_belongs_to_bootstrap_without_org_admin_runtime_role(self):
        bootstrap = (ROOT / "bootstrap" / "identity" / "main.tf").read_text()
        self.assertIn('"orgpolicy.googleapis.com"', bootstrap)
        self.assertIn('"roles/compute.securityAdmin"', bootstrap)
        self.assertNotIn('"roles/orgpolicy.policyAdmin"', bootstrap)

    def test_service_vm_depends_on_policy_only_when_policy_is_managed(self):
        spec = importlib.util.spec_from_file_location("gcp_generate", ROOT / "scripts" / "generate.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        manifest = {
            "global": {"environment": "prod", "project_id": "open-platform-prod",
                       "region": "asia-east1", "network_name": "web-saas-prod-gcp", "subnet_cidr": "10.73.0.0/24",
                       "spot_ssh_source_ranges": ["203.0.113.1/32"], "spot_network_tags": ["web-saas-ssh"],
                       "external_ip_allowed_instances": [{"name": "web-saas-prod", "zone": "asia-east1-a"}]},
            "spot_vms": [{"name": "web-saas-prod", "zone": "asia-east1-a", "machine_type": "e2-medium", "public_ip": True, "network_tags": ["web-saas-ssh"]}],
        }
        for managed in (True, False):
            manifest["global"]["manage_external_ip_policy"] = managed
            with tempfile.TemporaryDirectory() as tempdir, patch.object(generator, "load_resources", return_value=manifest):
                generator.render(SimpleNamespace(resources="ignored", workdir=tempdir))
                rendered = (Path(tempdir) / "generated_platform.tf").read_text()
            vm = rendered.split('module "spot_web_saas_prod" {', 1)[1].split("\n}", 1)[0]
            if managed:
                self.assertIn('google_org_policy_policy.vm_external_ip_access', vm)
            else:
                self.assertNotIn('google_org_policy_policy.vm_external_ip_access', vm)

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
        self.assertIn('parent = "projects/${module.project.project_id}"', rendered)
        self.assertIn('ignore_changes = [name]', rendered)
        # Imported PROD V2 policy parents use a project number. Selecting this
        # explicitly must not change the default of other existing namespaces.
        manifest["spec"]["external_ip_policy_parent_identity"] = "project_number"
        with tempfile.TemporaryDirectory() as tempdir, patch.object(generator, "load_resources", return_value=manifest):
            generator.render(SimpleNamespace(resources="ignored", workdir=tempdir))
            numeric = (Path(tempdir) / "generated_platform.tf").read_text(encoding="utf-8")
        self.assertIn('parent = "projects/${module.project.project_number}"', numeric)
        self.assertNotIn('parent = "projects/${module.project.project_id}"', numeric)
        manifest["spec"]["external_ip_policy_parent_identity"] = "invalid"
        with tempfile.TemporaryDirectory() as tempdir, patch.object(generator, "load_resources", return_value=manifest):
            with self.assertRaises(SystemExit):
                generator.render(SimpleNamespace(resources="ignored", workdir=tempdir))
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
        with tempfile.TemporaryDirectory() as tempdir:
            with patch.object(generator, "load_resources", return_value=manifest):
                generator.render(SimpleNamespace(resources="ignored", workdir=tempdir))
            rendered = (Path(tempdir) / "generated_platform.tf").read_text(encoding="utf-8")
        self.assertIn('resource "google_compute_firewall" "vault_gateway_https"', rendered)
        self.assertIn('ports    = ["443"]', rendered)

    def test_public_spot_vm_has_configurable_ssh_and_no_forced_hourly_expiry(self):
        module = (ROOT / "modules" / "spot_vm" / "main.tf").read_text(encoding="utf-8")
        template = (ROOT / "templates" / "open-platform.tf.j2").read_text(encoding="utf-8")
        generator = (ROOT / "scripts" / "generate.py").read_text(encoding="utf-8")

        self.assertIn('default     = null', module)
        self.assertIn('var.max_run_duration_seconds == null ? true :', module)
        self.assertIn('instance_termination_action = var.provisioning_model == "SPOT" ? "STOP" : null', module)
        self.assertIn('for_each = var.max_run_duration_seconds == null ? []', module)
        self.assertIn('condition     = !var.public_ip || var.enable_oslogin || trimspace(var.ssh_public_key) != ""', module)
        self.assertIn('var.enable_oslogin || trimspace(var.ssh_public_key) == "" ? {} : {', module)
        self.assertIn('variable "enable_oslogin"', module)
        self.assertIn('var.enable_oslogin ? { "enable-oslogin" = "TRUE" } : {}', module)
        self.assertNotIn('"enable-oslogin" = "FALSE"', module)
        self.assertIn('public_ip       = {{ vm.public_ip | default(false) | tojson }}', template)
        self.assertIn('enable_oslogin  = {{ vm.enable_oslogin | default(false) | tojson }}', template)
        self.assertIn('source_ranges = {{ spot_ssh_source_ranges | tojson }}', template)
        self.assertIn('ssh_public_key  = var.ssh_public_key', template)
        self.assertIn('"groups": vm.get("inventory_groups", [])', generator)
        self.assertIn('network_tags    = {{ vm.network_tags | default([]) | tojson }}', template)
        self.assertIn('"ip": address', generator)
        self.assertNotIn('"spot_ssh_source_ranges",', generator.split('declared = {', 1)[1].split('}', 1)[0])

    def test_persistent_service_vm_keeps_address_and_protects_separate_disk(self):
        spec = importlib.util.spec_from_file_location("gcp_generate", ROOT / "scripts" / "generate.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        vm = {
            "name": "web-saas-uat", "zone": "asia-east1-a", "machine_type": "e2-medium",
            "provisioning_model": "STANDARD", "deletion_protection": True,
            "enable_oslogin": True, "public_ip": True, "network_tags": ["web-saas-ssh"],
            "inventory_groups": ["web_saas"],
            "data_disk": {"name": "web-saas-uat-data", "size_gb": 100,
                          "type": "pd-balanced", "device_name": "web-saas-data",
                          "mount_path": "/data"},
        }
        manifest = {
            "kind": "GCPWorkloadNamespace",
            "metadata": {"name": "web-saas", "environment": "uat", "provider": "gcp"},
            "spec": {
                "gcp_account_id": "xworktech", "project_id": "open-platform-uat",
                "state_project": "svc.plus", "organization_id": "744119519286",
                "region": "asia-east1", "workspace": "web-saas", "state_namespace": "web-saas",
                "network_name": "web-saas-uat-gcp", "subnet_cidr": "10.63.0.0/24",
                "spot_ssh_source_ranges": ["203.0.113.1/32"],
                "spot_network_tags": ["web-saas-ssh"],
                "state": {"key": "terraform/uat/svc.plus/gcp-cloud/xworktech/web-saas/terraform.tfstate"},
                "resource": {"lifecycle": "persistent"},
                "resources": {"service_vms": [vm]},
            },
        }
        _, _, vms, _, _ = generator.normalize_resources(manifest)
        self.assertEqual(vms[0]["name"], "web-saas-uat")
        with tempfile.TemporaryDirectory() as tempdir, patch.object(generator, "load_resources", return_value=manifest):
            generator.render(SimpleNamespace(resources="ignored", workdir=tempdir))
            rendered = (Path(tempdir) / "generated_platform.tf").read_text(encoding="utf-8")
        self.assertIn('module "spot_web_saas_uat"', rendered)
        self.assertIn('module "data_disk_web_saas_uat"', rendered)
        self.assertRegex(rendered, r'data_disk_id\s+= module\.data_disk_web_saas_uat\.id')
        self.assertRegex(rendered, r'provisioning_model\s+= "STANDARD"')
        self.assertRegex(rendered, r'deletion_protection\s+= true')
        disk_module = (ROOT / "modules" / "persistent_data_disk" / "main.tf").read_text()
        self.assertIn('deletion_policy = "PREVENT"', disk_module)
        self.assertIn('prevent_destroy = true', disk_module)

        manifest["spec"]["resources"]["service_vms"][0]["deletion_protection"] = False
        with self.assertRaises(SystemExit):
            generator.normalize_resources(manifest)

    def test_retained_data_disk_attaches_to_declared_vm_without_changing_vm_module(self):
        spec = importlib.util.spec_from_file_location("gcp_generate", ROOT / "scripts" / "generate.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        vm = {
            "name": "web-saas-uat", "zone": "asia-east1-a", "machine_type": "e2-medium",
            "enable_oslogin": False, "public_ip": True, "network_tags": ["web-saas-ssh"],
            "inventory_groups": ["web_saas"],
        }
        manifest = {
            "kind": "GCPWorkloadNamespace",
            "metadata": {"name": "web-saas", "environment": "uat", "provider": "gcp"},
            "spec": {
                "gcp_account_id": "xworktech", "project_id": "open-platform-uat",
                "state_project": "svc.plus", "organization_id": "744119519286",
                "region": "asia-east1", "workspace": "web-saas", "state_namespace": "web-saas",
                "network_name": "web-saas-uat-gcp", "subnet_cidr": "10.63.0.0/24",
                "spot_ssh_source_ranges": ["203.0.113.1/32"],
                "spot_network_tags": ["web-saas-ssh"],
                "state": {"key": "terraform/uat/svc.plus/gcp-cloud/xworktech/web-saas/terraform.tfstate"},
                "resources": {
                    "spot_vms": [vm],
                    "persistent_data_disks": [{
                        "name": "web-saas-uat-data", "zone": "asia-east1-a", "size_gb": 100,
                        "type": "pd-balanced", "instance": "web-saas-uat",
                        "device_name": "web-saas-data", "mount_path": "/data",
                    }],
                },
            },
        }
        with tempfile.TemporaryDirectory() as tempdir, patch.object(generator, "load_resources", return_value=manifest):
            generator.render(SimpleNamespace(resources="ignored", workdir=tempdir))
            rendered = (Path(tempdir) / "generated_platform.tf").read_text(encoding="utf-8")

        self.assertIn('module "retained_data_disk_web_saas_uat_data"', rendered)
        self.assertIn('resource "google_compute_attached_disk" "retained_data_disk_web_saas_uat_data"', rendered)
        self.assertIn('depends_on  = [module.spot_web_saas_uat]', rendered)
        self.assertIn('instance    = module.spot_web_saas_uat.self_link', rendered)
        self.assertIn('device_name = "web-saas-data"', rendered)
        vm_module = rendered.split('module "spot_web_saas_uat" {', 1)[1].split("\n}", 1)[0]
        self.assertNotIn("data_disk_id", vm_module)
        self.assertNotIn("attached_disk", vm_module)

        # Promote compute while preserving the independently managed disk's
        # resource identity. Rendering does not prove no live VM replacement.
        vm.update(provisioning_model="STANDARD", deletion_protection=True)
        manifest["spec"]["resources"]["service_vms"] = manifest["spec"]["resources"].pop("spot_vms")
        manifest["spec"]["resource"] = {"lifecycle": "persistent"}
        with tempfile.TemporaryDirectory() as tempdir, patch.object(generator, "load_resources", return_value=manifest):
            generator.render(SimpleNamespace(resources="ignored", workdir=tempdir))
            persistent_rendered = (Path(tempdir) / "generated_platform.tf").read_text(encoding="utf-8")
        self.assertIn('module "retained_data_disk_web_saas_uat_data"', persistent_rendered)
        self.assertNotIn('module "data_disk_web_saas_uat"', persistent_rendered)
        self.assertIn('module "spot_web_saas_uat"', persistent_rendered)
        self.assertRegex(persistent_rendered, r'provisioning_model\s+= "STANDARD"')
        self.assertRegex(persistent_rendered, r'deletion_protection\s+= true')
        for mutation in ("no_disk", "wrong_instance", "no_protection", "invalid_disk"):
            import copy
            candidate = copy.deepcopy(manifest)
            if mutation == "no_disk": candidate["spec"]["resources"]["persistent_data_disks"] = []
            elif mutation == "wrong_instance": candidate["spec"]["resources"]["persistent_data_disks"][0]["instance"] = "other-vm"
            elif mutation == "no_protection": candidate["spec"]["resources"]["service_vms"][0]["deletion_protection"] = False
            else: candidate["spec"]["resources"]["persistent_data_disks"][0]["size_gb"] = 0
            with self.subTest(mutation=mutation), self.assertRaises(SystemExit):
                generator.normalize_resources(candidate)
        spot_vm_module = (ROOT / "modules" / "spot_vm" / "main.tf").read_text(encoding="utf-8")
        self.assertIn("ignore_changes = [attached_disk]", spot_vm_module)
        self.assertIn("persistent_data_disks = [", rendered)

        runtime = {
            "project_id": "open-platform-uat",
            "spot_instances": {
                "web-saas-uat": {
                    "public_ip": "35.187.147.104", "private_ip": "10.63.0.9",
                    "zone": "asia-east1-a", "provisioning_model": "SPOT",
                    "persistent_data_disks": [{
                        "name": "web-saas-uat-data", "id": "disk-resource-id",
                    }],
                },
            },
        }
        with tempfile.TemporaryDirectory() as tempdir, patch.object(
            generator, "load_resources", return_value=manifest
        ), patch.object(generator.subprocess, "check_output", return_value=json.dumps(runtime)):
            generator.inventory(SimpleNamespace(resources="ignored", workdir=tempdir))
            cmdb = json.loads((Path(tempdir) / "cmdb.json").read_text(encoding="utf-8"))
        host = cmdb["web-saas-uat"]
        self.assertNotIn("data_disk", host)
        self.assertEqual(host["persistent_data_disks"], [{
            "name": "web-saas-uat-data", "id": "disk-resource-id", "zone": "asia-east1-a",
            "device_name": "web-saas-data", "mount_path": "/data",
            "management": "google_compute_attached_disk",
        }])

    def test_retained_data_disk_rejects_unmatched_vm_identity(self):
        spec = importlib.util.spec_from_file_location("gcp_generate", ROOT / "scripts" / "generate.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        manifest = {
            "kind": "GCPWorkloadNamespace",
            "metadata": {"name": "web-saas", "environment": "uat", "provider": "gcp"},
            "spec": {
                "gcp_account_id": "xworktech", "project_id": "open-platform-uat",
                "state_project": "svc.plus", "organization_id": "744119519286",
                "region": "asia-east1", "workspace": "web-saas", "state_namespace": "web-saas",
                "network_name": "web-saas-uat-gcp", "subnet_cidr": "10.63.0.0/24",
                "state": {"key": "terraform/uat/svc.plus/gcp-cloud/xworktech/web-saas/terraform.tfstate"},
                "resources": {
                    "spot_vms": [{"name": "web-saas-uat", "zone": "asia-east1-a", "machine_type": "e2-medium"}],
                    "persistent_data_disks": [{
                        "name": "web-saas-uat-data", "zone": "asia-east1-b", "size_gb": 100,
                        "instance": "web-saas-uat", "device_name": "web-saas-data", "mount_path": "/data",
                    }],
                },
            },
        }
        with self.assertRaisesRegex(SystemExit, "declared VM with the same zone"):
            generator.normalize_resources(manifest)
        manifest["spec"]["resources"]["persistent_data_disks"][0]["zone"] = "asia-east1-a"
        manifest["spec"]["resources"]["spot_vms"][0]["data_disk"] = {
            "name": "legacy-data", "size_gb": 100, "device_name": "legacy-data",
            "mount_path": "/data",
        }
        with self.assertRaisesRegex(SystemExit, "both legacy data_disk and persistent_data_disks"):
            generator.normalize_resources(manifest)

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

    def test_private_spot_instance_uses_iap_inventory_and_firewall(self):
        generator = self.load_generator()
        manifest = {
            "kind": "GCPWorkloadNamespace",
            "metadata": {"name": "private-sample", "environment": "uat", "provider": "gcp"},
            "spec": {
                "gcp_account_id": "test-account", "project_id": "test-project",
                "organization_id": "123", "region": "asia-east1", "workspace": "private-sample",
                "state_namespace": "private-sample", "network_name": "private-net",
                "state": {"key": "terraform/uat/test-project/gcp-cloud/test-account/private-sample/terraform.tfstate"},
                "subnet_cidr": "10.40.0.0/24", "enable_iap_ssh": True, "enable_oslogin": True,
                "spot_network_tags": ["private-ssh"], "ssh_username": "deployer",
                "resources": {"spot_vms": [{
                    "name": "private-vm", "zone": "asia-east1-a", "machine_type": "e2-custom-4-8192",
                    "public_ip": False, "network_tags": ["private-ssh"], "enable_oslogin": True,
                    "inventory_groups": ["ai_workspace"],
                }]},
            },
        }
        runtime = {"project_id": "test-project", "spot_instances": {"private-vm": {
            "private_ip": "10.40.0.10", "public_ip": None, "zone": "asia-east1-a", "provisioning_model": "SPOT",
        }}}
        with tempfile.TemporaryDirectory() as tempdir, patch.object(
            generator, "load_resources", return_value=manifest
        ), patch.object(generator.subprocess, "check_output", return_value=json.dumps(runtime)), patch.dict(
            generator.os.environ,
            {"GCP_OSLOGIN_USERNAME": "sa_123456789012345678901", "GCP_SSH_PRIVATE_KEY_FILE": "/tmp/one-run-key"},
        ):
            generator.render(SimpleNamespace(resources="ignored", workdir=tempdir))
            generator.inventory(SimpleNamespace(resources="ignored", workdir=tempdir))
            rendered = (Path(tempdir) / "generated_platform.tf").read_text(encoding="utf-8")
            inventory = (Path(tempdir) / "inventory.ini").read_text(encoding="utf-8")
        self.assertIn('resource "google_iap_tunnel_instance_iam_member" "spot_iap_tunnel_private_vm"', rendered)
        self.assertIn('source_ranges = ["35.235.240.0/20"]', rendered)
        self.assertIn("private-vm ansible_host=10.40.0.10", inventory)
        self.assertIn("gcloud compute start-iap-tunnel private-vm 22", inventory)
        self.assertIn("ansible_ssh_private_key_file=/tmp/one-run-key", inventory)

    def oslogin_manifest(self):
        return {
            "kind": "GCPWorkloadNamespace",
            "metadata": {"name": "sample", "environment": "uat", "provider": "gcp"},
            "spec": {
                "gcp_account_id": "test-account", "project_id": "test-project",
                "organization_id": "123", "region": "asia-east1", "workspace": "sample",
                "state_namespace": "sample", "network_name": "sample-net",
                "state": {"key": "terraform/uat/test-project/gcp-cloud/test-account/sample/terraform.tfstate"},
                "subnet_cidr": "10.40.0.0/24", "spot_ssh_source_ranges": ["203.0.113.10/32"],
                "spot_network_tags": ["sample-ssh"], "ssh_username": "deployer",
                "resources": {"spot_vms": [
                    {
                        "name": "sample-vm", "zone": "asia-east1-a", "machine_type": "e2-custom-4-8192",
                        "public_ip": True, "network_tags": ["sample-ssh"], "enable_oslogin": True,
                        "inventory_groups": ["ai_workspace"],
                    },
                    {
                        "name": "legacy-vm", "zone": "asia-east1-a", "machine_type": "e2-small",
                        "public_ip": True, "network_tags": ["sample-ssh"],
                        "inventory_groups": ["legacy"],
                    },
                ]},
            },
        }

    def load_generator(self):
        spec = importlib.util.spec_from_file_location("gcp_generate", ROOT / "scripts" / "generate.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        return generator

    def test_oslogin_spot_vm_grants_instance_admin_login_only_where_declared(self):
        generator = self.load_generator()
        with tempfile.TemporaryDirectory() as tempdir, patch.object(
            generator, "load_resources", return_value=self.oslogin_manifest()
        ):
            generator.render(SimpleNamespace(resources="ignored", workdir=tempdir))
            rendered = (Path(tempdir) / "generated_platform.tf").read_text(encoding="utf-8")
            manifest = json.loads((Path(tempdir) / "resources_manifest.json").read_text(encoding="utf-8"))
        self.assertIn('resource "google_compute_instance_iam_member" "spot_os_admin_login_sample_vm"', rendered)
        self.assertIn("instance_name = module.spot_sample_vm.name", rendered)
        self.assertIn('role          = "roles/compute.osAdminLogin"', rendered)
        self.assertNotIn("spot_os_admin_login_legacy_vm", rendered)
        self.assertNotIn('"roles/compute.osAdmin"', rendered)
        self.assertNotIn("google_project_iam_member", rendered)
        self.assertEqual([vm.get("enable_oslogin") for vm in manifest["spot_vms"]], [True, None])

    def test_oslogin_spot_vm_inventory_uses_the_deploy_principal_username(self):
        generator = self.load_generator()
        runtime = {"project_id": "test-project", "spot_instances": {
            "sample-vm": {"public_ip": "198.51.100.10", "provisioning_model": "SPOT"},
            "legacy-vm": {"public_ip": "198.51.100.11", "provisioning_model": "SPOT"},
        }}
        with tempfile.TemporaryDirectory() as tempdir, patch.object(
            generator, "load_resources", return_value=self.oslogin_manifest()
        ), patch.object(generator.subprocess, "check_output", return_value=json.dumps(runtime)), patch.dict(
            generator.os.environ, {"GCP_OSLOGIN_USERNAME": "sa_123456789012345678901"}
        ):
            generator.inventory(SimpleNamespace(resources="ignored", workdir=tempdir))
            cmdb = json.loads((Path(tempdir) / "cmdb.json").read_text(encoding="utf-8"))
            inventory = (Path(tempdir) / "inventory.ini").read_text(encoding="utf-8")
        self.assertEqual(cmdb["sample-vm"]["ansible_user"], "sa_123456789012345678901")
        self.assertEqual(cmdb["legacy-vm"]["ansible_user"], "deployer")
        self.assertIn("sample-vm ansible_host=198.51.100.10 ansible_user=sa_123456789012345678901", inventory)
        self.assertIn("legacy-vm ansible_host=198.51.100.11 ansible_user=deployer", inventory)

    def test_oslogin_spot_vm_inventory_refuses_a_missing_or_invalid_username(self):
        generator = self.load_generator()
        runtime = {"project_id": "test-project", "spot_instances": {
            "sample-vm": {"public_ip": "198.51.100.10"},
            "legacy-vm": {"public_ip": "198.51.100.11"},
        }}
        for value in ("", "root;id", "Sa_UPPER"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tempdir, patch.object(
                generator, "load_resources", return_value=self.oslogin_manifest()
            ), patch.object(generator.subprocess, "check_output", return_value=json.dumps(runtime)), patch.dict(
                generator.os.environ, {"GCP_OSLOGIN_USERNAME": value}
            ):
                with self.assertRaisesRegex(SystemExit, "GCP_OSLOGIN_USERNAME"):
                    generator.inventory(SimpleNamespace(resources="ignored", workdir=tempdir))

    def test_resource_inventory_resolves_the_exact_wif_service_account_profile(self):
        generator = self.load_generator()
        account = "github-actions-prod@test-project.iam.gserviceaccount.com"
        runtime = {"project_id": "test-project", "deploy_account": account, "spot_instances": {
            "sample-vm": {"public_ip": "198.51.100.10", "provisioning_model": "STANDARD"},
            "legacy-vm": {"public_ip": "198.51.100.11", "provisioning_model": "STANDARD"},
        }}
        profile = {"posixAccounts": [{"operatingSystemType": "LINUX", "username": "sa_123"}]}
        with tempfile.TemporaryDirectory() as tempdir, patch.object(
            generator, "load_resources", return_value=self.oslogin_manifest()
        ), patch.dict(generator.os.environ, {}, clear=True), patch.object(
            generator.subprocess, "check_output", return_value=json.dumps(runtime)
        ), patch.object(generator, "get_oslogin_profile", return_value=profile) as lookup:
            generator.inventory(SimpleNamespace(resources="ignored", workdir=tempdir))
            cmdb = json.loads((Path(tempdir) / "cmdb.json").read_text())
        self.assertEqual(cmdb["sample-vm"]["ansible_user"], "sa_123")
        lookup.assert_called_once_with("test-project", account)

    def test_profile_resolution_refuses_missing_ambiguous_personal_and_invalid_users(self):
        generator = self.load_generator()
        profiles = [
            {}, {"posixAccounts": []},
            {"posixAccounts": [{"operatingSystemType": "LINUX", "username": "personal"}]},
            {"posixAccounts": [{"operatingSystemType": "LINUX", "username": "sa_1;id"}]},
            {"posixAccounts": [{"operatingSystemType": "LINUX", "username": f"sa_{i}"} for i in (1, 2)]},
        ]
        for profile in profiles:
            with self.subTest(profile=profile), patch.dict(generator.os.environ, {}, clear=True), patch.object(
                generator, "get_oslogin_profile", return_value=profile
            ):
                with self.assertRaisesRegex(SystemExit, "unique Linux OS Login"):
                    generator.oslogin_username("test-project", "github-actions-prod@test-project.iam.gserviceaccount.com")

    def test_profile_resolution_refuses_foreign_or_personal_principal_before_cloud_access(self):
        generator = self.load_generator()
        for account in (None, "personal@example.com", "github-actions-prod@other-project.iam.gserviceaccount.com"):
            with self.subTest(account=account), patch.dict(generator.os.environ, {}, clear=True), patch.object(
                generator.subprocess, "check_output"
            ) as command:
                with self.assertRaisesRegex(SystemExit, "verified runtime project"):
                    generator.oslogin_username("test-project", account)
                command.assert_not_called()

    def test_profile_lookup_activates_only_the_exact_github_wif_credential(self):
        generator = self.load_generator()
        account = "github-actions-prod@test-project.iam.gserviceaccount.com"
        credential = {"type": "external_account", "service_account_impersonation_url":
                      f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{account}:generateAccessToken"}
        profile = {"posixAccounts": [{"operatingSystemType": "LINUX", "username": "sa_123"}]}
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "github-wif.json"
            path.write_text(json.dumps(credential))
            with patch.dict(generator.os.environ, {"GOOGLE_GHA_CREDS_PATH": str(path)}, clear=True), patch.object(
                generator.subprocess, "run"
            ) as activate, patch.object(generator, "get_oslogin_profile", return_value=profile):
                self.assertEqual(generator.oslogin_username("test-project", account), "sa_123")
                self.assertEqual(activate.call_args.args[0], ["gcloud", "--quiet", "auth", "login", f"--cred-file={path}"])
                self.assertTrue(activate.call_args.kwargs["check"])
                self.assertEqual(activate.call_args.kwargs["timeout"], 60)

    def test_first_profile_initialization_requires_exact_wif_and_requeries_after_revocation(self):
        generator = self.load_generator()
        account = "github-actions-prod@test-project.iam.gserviceaccount.com"
        credential = {"type": "external_account", "service_account_impersonation_url":
                      f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{account}:generateAccessToken"}
        profile = {"posixAccounts": [{"operatingSystemType": "LINUX", "username": "sa_123"}]}
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "github-wif.json"
            path.write_text(json.dumps(credential))
            with patch.dict(generator.os.environ, {"GOOGLE_GHA_CREDS_PATH": str(path)}, clear=True), patch.object(
                generator.subprocess, "run"
            ) as commands, patch.object(generator, "get_oslogin_profile", side_effect=[{}, profile]) as query:
                self.assertEqual(generator.oslogin_username("test-project", account), "sa_123")
                self.assertEqual(commands.call_count, 2)
                initialize = commands.call_args_list[1]
                self.assertEqual(initialize.args[0], ["bash", str(generator.ROOT.parents[1] / "scripts/pipeline/initialize-gcp-oslogin-profile.sh"), "test-project", account])
                self.assertTrue(initialize.kwargs["check"])
                self.assertEqual(initialize.kwargs["timeout"], 75)
                self.assertEqual(query.call_count, 2)

    def test_first_profile_failed_cleanup_refuses_inventory(self):
        generator = self.load_generator()
        account = "github-actions-prod@test-project.iam.gserviceaccount.com"
        credential = {"type": "external_account", "service_account_impersonation_url":
                      f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{account}:generateAccessToken"}
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "github-wif.json"
            path.write_text(json.dumps(credential))
            with patch.dict(generator.os.environ, {"GOOGLE_GHA_CREDS_PATH": str(path)}, clear=True), patch.object(
                generator.subprocess, "run", side_effect=[None, generator.subprocess.CalledProcessError(1, [])]
            ), patch.object(generator, "get_oslogin_profile", return_value={}) as query:
                with self.assertRaisesRegex(SystemExit, "initialization or temporary key revocation failed"):
                    generator.oslogin_username("test-project", account)
                self.assertEqual(query.call_count, 1)

    def test_profile_lookup_refuses_other_credential_types_or_wif_principals(self):
        generator = self.load_generator()
        credentials = [
            {"type": "authorized_user"}, {"type": "service_account"},
            {"type": "external_account", "service_account_impersonation_url": "https://other.example.com"},
        ]
        for credential in credentials:
            with self.subTest(type=credential["type"]), tempfile.TemporaryDirectory() as tempdir:
                path = Path(tempdir) / "wrong-credential.json"
                path.write_text(json.dumps(credential))
                with patch.dict(generator.os.environ, {"GOOGLE_GHA_CREDS_PATH": str(path)}, clear=True), patch.object(
                    generator.subprocess, "run"
                ) as activate, patch.object(generator.subprocess, "check_output") as lookup:
                    with self.assertRaisesRegex(SystemExit, "Cannot activate the exact runtime"):
                        generator.oslogin_username("test-project", "github-actions-prod@test-project.iam.gserviceaccount.com")
                    activate.assert_not_called()
                    lookup.assert_not_called()

    def test_profile_lookup_failure_does_not_expose_cloud_errors(self):
        generator = self.load_generator()
        with patch.dict(generator.os.environ, {}, clear=True), patch.object(
            generator.subprocess, "check_output", side_effect=generator.subprocess.CalledProcessError(1, [], stderr="private details")
        ):
            with self.assertRaisesRegex(SystemExit, "^OS Login profile query failed for the exact authenticated runtime service account$"):
                generator.oslogin_username("test-project", "github-actions-prod@test-project.iam.gserviceaccount.com")

    def test_profile_api_explicitly_binds_project_and_runtime_principal(self):
        generator = self.load_generator()
        profile = {"posixAccounts": [{"operatingSystemType": "LINUX", "username": "sa_123"}]}
        with patch.object(generator.subprocess, "check_output", return_value="fixture-access-token\n") as token, patch.object(
            generator.urllib.request, "urlopen"
        ) as api:
            api.return_value.__enter__.return_value = io.StringIO(json.dumps(profile))
            self.assertEqual(generator.get_oslogin_profile("test-project", "github-actions-prod@test-project.iam.gserviceaccount.com"), profile)
        token.assert_called_once_with(
            ["gcloud", "auth", "print-access-token", "--account=github-actions-prod@test-project.iam.gserviceaccount.com"],
            text=True, stderr=generator.subprocess.DEVNULL, timeout=60,
        )
        request = api.call_args.args[0]
        self.assertEqual(request.full_url, "https://oslogin.googleapis.com/v1/users/github-actions-prod%40test-project.iam.gserviceaccount.com/loginProfile?projectId=test-project")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer fixture-access-token")
        self.assertEqual(api.call_args.kwargs["timeout"], 15)

    def test_profile_api_errors_report_only_bounded_status_metadata(self):
        generator = self.load_generator()
        with patch.dict(generator.os.environ, {}, clear=True), patch.object(
            generator, "get_oslogin_profile", side_effect=generator.urllib.error.HTTPError("private-url",403,"private-message",{},None)
        ):
            with self.assertRaisesRegex(SystemExit,"^OS Login profile API request failed: HTTP 403$"):
                generator.oslogin_username("test-project","github-actions-prod@test-project.iam.gserviceaccount.com")

    def test_inventory_refuses_a_foreign_runtime_project_before_profile_lookup(self):
        generator = self.load_generator()
        with tempfile.TemporaryDirectory() as tempdir, patch.object(
            generator, "load_resources", return_value=self.oslogin_manifest()
        ), patch.object(generator.subprocess, "check_output", return_value='{"project_id":"other-project"}') as command:
            with self.assertRaisesRegex(SystemExit, "runtime project differs"):
                generator.inventory(SimpleNamespace(resources="ignored", workdir=tempdir))
            self.assertEqual(command.call_count, 1)
            self.assertFalse((Path(tempdir) / "cmdb.json").exists())

    def test_spot_vm_enable_oslogin_must_be_boolean(self):
        generator = self.load_generator()
        manifest = self.oslogin_manifest()
        manifest["spec"]["resources"]["spot_vms"][0]["enable_oslogin"] = "true"
        with self.assertRaisesRegex(SystemExit, "enable_oslogin must be a boolean"):
            generator.normalize_resources(manifest)


if __name__ == "__main__":
    unittest.main()
