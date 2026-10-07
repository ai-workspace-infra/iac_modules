"""Validate reusable action closure and embedded scripts without authentication."""
import ast
import re
import subprocess
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]

class ActionContracts(unittest.TestCase):
    @staticmethod
    def action_files():
        actions = ROOT / '.github/actions'
        return [
            *actions.glob('iac-*/action.yml'),
            *actions.glob('auth-*/action.yml'),
            actions / 'node-access-gcp/action.yml',
            actions / 'gitops-gcp-target/action.yml',
            actions / 'gitops-aws-oidc/action.yml',
            actions / 'cloud-run-serving-facts/action.yml',
        ]

    def test_local_action_dependencies_and_inputs_exist(self):
        for file in self.action_files():
            action = yaml.safe_load(file.read_text())
            self.assertEqual(action['runs']['using'], 'composite', file)
            for step in action['runs']['steps']:
                uses = step.get('uses', '')
                if uses.startswith('./iac_modules/'):
                    dependency = ROOT / uses.removeprefix('./iac_modules/') / 'action.yml'
                    self.assertTrue(dependency.is_file(), dependency)
                    inputs = yaml.safe_load(dependency.read_text()).get('inputs', {})
                    self.assertFalse(set(step.get('with', {})) - set(inputs), file)
                    self.assertFalse({k for k, v in inputs.items() if v.get('required') and 'default' not in v} - set(step.get('with', {})), file)

    def test_shell_and_embedded_python_are_parseable(self):
        for file in self.action_files():
            for step in yaml.safe_load(file.read_text())['runs']['steps']:
                if 'run' not in step:
                    continue
                source = re.sub(r'\$\{\{.*?\}\}', 'VALUE', step['run'])
                result = subprocess.run(['bash', '-n'], input=source, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, f'{file}: {result.stderr}')
                for code in re.findall(r"python3 - <<'PYCODE'\n(.*?)\nPYCODE", source, re.S):
                    ast.parse(code, filename=str(file))

    def test_gcp_node_owner_uses_strict_existing_access_implementation(self):
        action = yaml.safe_load((ROOT / '.github/actions/node-access-gcp/action.yml').read_text())
        source = '\n'.join(step.get('run', '') for step in action['runs']['steps'])
        self.assertIn('gcp-temporary-ssh-access.sh', source)
        self.assertIn('resolve_gcp_vault.py', source)
        self.assertIn('resolve_gcp_vault_source.py', source)
        self.assertIn('OSLOGIN_KEY_TTL: 65m', (ROOT / '.github/actions/node-access-gcp/action.yml').read_text())
        self.assertNotIn('0.0.0.0/0', source)
        auth = next(step for step in action['runs']['steps'] if step.get('uses') == './iac_modules/.github/actions/auth-gcp-cloud')
        self.assertEqual(auth['with']['load-state-contract'], 'false')

    def test_gcp_auth_binds_optional_state_only_when_requested(self):
        action = yaml.safe_load((ROOT / '.github/actions/auth-gcp-cloud/action.yml').read_text())
        bind = next(step for step in action['runs']['steps'] if step.get('name') == 'Bind the reviewed Terraform state contract')
        self.assertEqual(bind['if'], "inputs.load-state-contract == 'true'")
        self.assertIn('STATE_SECRET_KEY', bind['env'])
        self.assertIn('TF_STATE_SECRET_KEY', bind['run'])

    def test_cloud_run_facts_do_not_invoke_docker(self):
        source = (ROOT / 'scripts/pipeline/cloud-run-serving-facts.sh').read_text()
        self.assertNotIn('docker buildx', source)
        self.assertIn('gcloud auth print-access-token', source)
        self.assertIn('/manifests/${ARTIFACT_DIGEST}', source)
