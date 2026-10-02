import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock


SCRIPT = Path(__file__).resolve().parents[1] / "adopt_uat_open_platform_vm.py"
SPEC = importlib.util.spec_from_file_location("open_platform_vm_adoption", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UatOpenPlatformVmAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.manifest = Path(self.tempdir.name) / "open-platform.yaml"
        self.manifest.write_text(
            """global:
  environment: uat
  project_id: open-platform-uat
  network_name: open-platform-uat
vault_nodes:
  - name: open-platform-uat
    zone: asia-east1-a
    machine_type: e2-medium
    public_ip: true
""",
            encoding="utf-8",
        )
        self.terraform_dir = Path(self.tempdir.name) / "terraform"

    def instance(self, **updates):
        result = {
            "name": "open-platform-uat",
            "zone": "https://www.googleapis.com/compute/v1/projects/open-platform-uat/zones/asia-east1-a",
            "machineType": "https://www.googleapis.com/compute/v1/projects/open-platform-uat/zones/asia-east1-a/machineTypes/e2-medium",
            "networkInterfaces": [
                {
                    "network": "https://www.googleapis.com/compute/v1/projects/open-platform-uat/global/networks/open-platform-uat",
                    "subnetwork": "https://www.googleapis.com/compute/v1/projects/open-platform-uat/regions/asia-east1/subnetworks/open-platform-uat-subnet",
                    "accessConfigs": [{"natIP": "35.201.195.123"}],
                }
            ],
            "serviceAccounts": [
                {"email": "open-platform-uat-runtime@open-platform-uat.iam.gserviceaccount.com"}
            ],
        }
        result.update(updates)
        return result

    def runner_for(self, instance, state_lists=("", MODULE.VM_ADDRESS)):
        state_list_count = 0
        commands = []

        def run(command, **kwargs):
            nonlocal state_list_count
            commands.append(command)
            if command[0] == "terraform" and command[-2:] == ["state", "list"]:
                output = state_lists[min(state_list_count, len(state_lists) - 1)]
                state_list_count += 1
                return CompletedProcess(command, 0, stdout=output, stderr="")
            if command[:4] == ["gcloud", "compute", "instances", "describe"]:
                if isinstance(instance, CompletedProcess):
                    return instance
                return CompletedProcess(command, 0, stdout=json.dumps(instance), stderr="")
            if command[:4] == ["gcloud", "compute", "addresses", "describe"]:
                return CompletedProcess(command, 0, stdout=json.dumps({"address": "35.201.195.123"}), stderr="")
            if command[0] == "terraform" and "import" in command:
                return CompletedProcess(command, 0, stdout="Import successful", stderr="")
            if command[0] == "terraform" and command[-4:-2] == ["state", "show"]:
                return CompletedProcess(
                    command,
                    0,
                    stdout='id = "projects/open-platform-uat/zones/asia-east1-a/instances/open-platform-uat"\n',
                    stderr="",
                )
            self.fail(f"Unexpected command: {command}")

        return Mock(side_effect=run), commands

    def test_imports_only_the_exact_gitops_declared_instance(self):
        runner, commands = self.runner_for(self.instance())
        result = MODULE.adopt_if_present(self.manifest, self.terraform_dir, runner)
        self.assertIn("Safely adopted", result)
        import_command = next(command for command in commands if "import" in command)
        self.assertEqual(import_command[-2], MODULE.VM_ADDRESS)
        self.assertEqual(
            import_command[-1],
            "projects/open-platform-uat/zones/asia-east1-a/instances/open-platform-uat",
        )

    def test_does_not_import_when_instance_is_absent(self):
        missing = CompletedProcess(
            ["gcloud"], 1, stdout="", stderr="The resource was not found"
        )
        runner, commands = self.runner_for(missing)
        result = MODULE.adopt_if_present(self.manifest, self.terraform_dir, runner)
        self.assertIn("Terraform will create it", result)
        self.assertFalse(any("import" in command for command in commands))

    def test_rejects_mismatched_instance_without_importing(self):
        runner, commands = self.runner_for(self.instance(machineType=".../machineTypes/e2-small"))
        with self.assertRaisesRegex(RuntimeError, "machine type differs"):
            MODULE.adopt_if_present(self.manifest, self.terraform_dir, runner)
        self.assertFalse(any("import" in command for command in commands))

    def test_rejects_manifest_pointing_outside_the_uat_project(self):
        self.manifest.write_text(
            self.manifest.read_text(encoding="utf-8").replace(
                "project_id: open-platform-uat", "project_id: open-platform-prod"
            ),
            encoding="utf-8",
        )
        runner, commands = self.runner_for(self.instance())
        with self.assertRaisesRegex(RuntimeError, "project_id=open-platform-uat"):
            MODULE.adopt_if_present(self.manifest, self.terraform_dir, runner)
        self.assertEqual(commands, [])

    def test_does_not_import_resource_already_in_state(self):
        runner, commands = self.runner_for(self.instance(), state_lists=(MODULE.VM_ADDRESS,))
        result = MODULE.adopt_if_present(self.manifest, self.terraform_dir, runner)
        self.assertIn("already manages", result)
        self.assertFalse(any("import" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
