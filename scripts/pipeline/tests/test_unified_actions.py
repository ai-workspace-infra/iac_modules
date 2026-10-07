"""Validate reusable action closure and embedded scripts without authentication."""
import ast
import re
import subprocess
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]

class ActionContracts(unittest.TestCase):
    def test_local_action_dependencies_and_inputs_exist(self):
        actions = ROOT / '.github/actions'
        for file in [*actions.glob('iac-*/action.yml'), *actions.glob('auth-*/action.yml')]:
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
        for file in [*(ROOT / '.github/actions').glob('iac-*/action.yml'), *(ROOT / '.github/actions').glob('auth-*/action.yml')]:
            for step in yaml.safe_load(file.read_text())['runs']['steps']:
                if 'run' not in step:
                    continue
                source = re.sub(r'\$\{\{.*?\}\}', 'VALUE', step['run'])
                result = subprocess.run(['bash', '-n'], input=source, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, f'{file}: {result.stderr}')
                for code in re.findall(r"python3 - <<'PYCODE'\n(.*?)\nPYCODE", source, re.S):
                    ast.parse(code, filename=str(file))
