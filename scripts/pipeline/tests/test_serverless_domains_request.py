import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('domains_request', ROOT / 'validate-serverless-domains-request.py')
owner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owner)
SHA = 'a' * 40
REPO = 'ai-workspace-infra/platform-ops-toolkit'
WORKFLOW = REPO + '/.github/workflows/serverless-orchestrator.yml@refs/heads/main'


def config():
    return {'kind': 'EdgeRoutingConfig', 'metadata': {'environment': 'prod', 'mode': 'serverless'},
            'spec': {'runtime': {'mode': 'serverless'}}}


class ServerlessDomainsTests(unittest.TestCase):
    def test_exact_production_contract(self):
        for mode in ('none', 'prod-cutover'):
            owner.validate(config(), 'prod', mode, SHA, SHA, REPO, WORKFLOW)

    def test_invalid_caller_ref_environment_and_dns_rejected(self):
        original = (config(), 'prod', 'none', SHA, SHA, REPO, WORKFLOW)
        for index, value in ((1, 'uat'), (2, 'uat-records'), (3, 'main'), (4, 'b'*40),
                             (5, 'foreign/repo'), (6, REPO + '/.github/workflows/hybrid-orchestrator.yml@refs/heads/main')):
            args = list(copy.deepcopy(original)); args[index] = value
            with self.assertRaises(ValueError): owner.validate(*args)

    def test_mode_mismatch_rejected(self):
        cfg = config(); cfg['spec']['runtime']['mode'] = 'selfhost'
        with self.assertRaises(ValueError): owner.validate(cfg, 'prod', 'none', SHA, SHA, REPO, WORKFLOW)

    def test_serverless_owner_does_not_invoke_api_alias_publication(self):
        action = (ROOT.parents[1] / '.github/actions/cloudflare-serverless-domains/action.yml').read_text()
        self.assertNotIn('cloudflare-api-aliases.py', action)
        workflow = (ROOT.parents[1] / '.github/workflows/cloudflare-serverless-domains.yml').read_text()
        self.assertLess(workflow.index('python3 scripts/pipeline/validate-serverless-domains-request.py'),
                        workflow.index('uses: hashicorp/vault-action'))
        self.assertIn('ref: ${{ job.workflow_sha }}', workflow)


if __name__ == '__main__': unittest.main()
