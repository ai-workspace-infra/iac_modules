import importlib.util
from pathlib import Path
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('caller',ROOT/'scripts/verify_feature_target_caller.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class CallerTest(unittest.TestCase):
    def test_requires_exact_main_caller_and_run_identity(self):
        repo='ai-workspace-infra/Platform-Orchestrator'
        env={'GITHUB_REPOSITORY':repo,'GITHUB_REF':'refs/heads/main',
             'GITHUB_WORKFLOW_REF':repo+'/.github/workflows/feature-lane-deploy.yml@refs/heads/main',
             'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}
        module.validate(env)
        for key,value in [('GITHUB_REPOSITORY','other/repo'),('GITHUB_REF','refs/heads/dev'),
                          ('GITHUB_WORKFLOW_REF',repo+'/.github/workflows/other.yml@refs/heads/main'),
                          ('GITHUB_SHA','main'),('GITHUB_RUN_ID','0'),('GITHUB_RUN_ATTEMPT','0')]:
            with self.subTest(key=key),self.assertRaises(ValueError):module.validate(dict(env,**{key:value}))

    def test_workflow_checks_caller_before_vault_and_pins_owner_source(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/feature-sit-target-observe.yml').read_text())
        job=workflow['jobs']['observe'];steps=job['steps']
        self.assertEqual(job['environment'],'dev')
        self.assertEqual(steps[0]['with']['repository'],'ai-workspace-infra/iac_modules')
        self.assertEqual(steps[0]['with']['ref'],'${{ job.workflow_sha }}')
        caller=next(i for i,step in enumerate(steps) if step.get('run')=='python3 scripts/verify_feature_target_caller.py')
        vault=next(i for i,step in enumerate(steps) if step.get('id')=='vault')
        self.assertLess(caller,vault)
        self.assertEqual(steps[vault]['with']['role'],'github-actions-feature-target-read-sit')
        self.assertIn('kv/data/sit/platform/akamai/feature-target',steps[vault]['with']['secrets'])

if __name__ == '__main__': unittest.main()
