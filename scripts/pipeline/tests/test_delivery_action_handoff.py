"""Exercise moved workflow/action contracts without Vault or provider access."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[3]


class DeliveryHandoff(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.iac = self.base / 'iac'
        self.gitops = self.base / 'gitops'
        for root in (self.iac, self.gitops):
            root.mkdir()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', '-C', str(root), 'config', 'user.name', 'Contract Test'], check=True)
            subprocess.run(['git', '-C', str(root), 'config', 'user.email', 'contract@example.invalid'], check=True)
        source = self.gitops / 'topology/uat/serverless/runtime-topology.yaml'
        source.parent.mkdir(parents=True)
        source.write_text(yaml.safe_dump({'kind': 'EdgeRoutingConfig', 'metadata': {'environment': 'uat', 'mode': 'serverless'},
                                         'spec': {'runtime': {'mode': 'serverless'}}}))
        fake = self.iac / 'scripts/akamai_state_preflight.py'
        fake.parent.mkdir()
        fake.write_text("import json\nfrom pathlib import Path\ndef main(args):\n    Path(args[args.index('--output')+1]).write_text(json.dumps({'status':'passed','mode':'read-only'}))\n    return 0\n")
        for root in (self.iac, self.gitops):
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(root), 'commit', '-qm', 'fixture'], check=True)
        self.env = dict(os.environ, IAC_ROOT=str(self.iac), GITOPS_DIR=str(self.gitops), GITOPS_ROOT=str(self.gitops),
                        GITOPS_REF=self.sha(self.gitops), GITOPS_SHA=self.sha(self.gitops), REQUESTED_ENVIRONMENT='uat',
                        SERVERLESS_DNS_MODE='none', RELEASE_REF='daily-build-2026.10.07', DOMAIN_PHASE='prepare',
                        CLOUDFLARE_BOUNDARY_CONFIG=str(self.base/'config.json'), DOMAIN_RECEIPT_FILE=str(self.base/'receipt.json'),
                        GITHUB_REPOSITORY='ai-workspace-infra/platform-ops-toolkit',
                        GITHUB_WORKFLOW_REF='ai-workspace-infra/platform-ops-toolkit/.github/workflows/serverless-orchestrator.yml@refs/heads/main',
                        GITHUB_RUN_ID='42', GITHUB_RUN_ATTEMPT='2', PREFLIGHT_ENVIRONMENT='uat', PREFLIGHT_ACCOUNT='account-one',
                        PREFLIGHT_CORRELATION_ID='42:2', PREFLIGHT_JSON_PATH=str(self.base/'preflight.json'))

    def sha(self, root):
        return subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()

    def run_script(self, script, **overrides):
        return subprocess.run(['python3', str(ROOT/'scripts/pipeline'/script)], env=dict(self.env, **overrides), capture_output=True, text=True)

    def test_domain_prepare_and_exact_receipt(self):
        self.assertEqual(self.run_script('serverless-domains-context.py').returncode, 0)
        result = self.run_script('serverless-domains-context.py', DOMAIN_PHASE='receipt')
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads((self.base/'receipt.json').read_text())
        self.assertEqual(receipt['owner_commit'], self.sha(self.iac))
        self.assertEqual(receipt['gitops_commit'], self.sha(self.gitops))
        self.assertEqual(receipt['run_attempt'], '2')

    def test_domain_changed_rendered_config_does_not_emit_acceptance(self):
        self.assertEqual(self.run_script('serverless-domains-context.py').returncode, 0)
        (self.base/'config.json').write_text('{}')
        self.assertNotEqual(self.run_script('serverless-domains-context.py', DOMAIN_PHASE='receipt').returncode, 0)
        self.assertFalse((self.base/'receipt.json').exists())

    def test_domain_wrong_caller_commit_scope_and_release_rejected(self):
        for key, value in [('GITHUB_WORKFLOW_REF', 'foreign/workflow@refs/heads/main'), ('GITOPS_REF', 'a'*40),
                           ('SERVERLESS_DNS_MODE', 'prod-cutover'), ('RELEASE_REF', 'main')]:
            with self.subTest(key=key):
                self.assertNotEqual(self.run_script('serverless-domains-context.py', **{key:value}).returncode, 0)

    def test_akamai_preflight_binds_owner_and_caller(self):
        result = self.run_script('akamai-preflight-action.py',
            GITHUB_WORKFLOW_REF='ai-workspace-infra/platform-ops-toolkit/.github/workflows/environment-data-operations.yml@refs/heads/main')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.base/'preflight.json').read_text())
        self.assertEqual(report['owner_commit'], self.sha(self.iac))
        self.assertEqual(report['run_id'], '42')

    def test_akamai_invalid_environment_or_caller_rejected_before_query(self):
        for overrides in [{'PREFLIGHT_ENVIRONMENT':'prod'}, {'PREFLIGHT_ACCOUNT':'../account'}, {'GITOPS_SHA':'a'*40}]:
            with self.subTest(overrides=overrides):
                env = dict(GITHUB_WORKFLOW_REF='ai-workspace-infra/platform-ops-toolkit/.github/workflows/environment-data-operations.yml@refs/heads/main', **overrides)
                self.assertNotEqual(self.run_script('akamai-preflight-action.py', **env).returncode, 0)
        self.assertFalse((self.base/'preflight.json').exists())


if __name__ == '__main__':
    unittest.main()
