"""Exercise shared selection, canonical keys and read-only lifecycle boundaries."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/pipeline'))
from unified.contracts import ContractError, canonical_state_key, load_targets, prepare, revalidate, validate_catalog_transition
SPEC = importlib.util.spec_from_file_location('catalog_preflight', ROOT / 'scripts/akamai_state_preflight.py')
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'gitops'
        self.iac = Path(self.tmp.name) / 'iac'
        for root in (self.root, self.iac):
            root.mkdir()
            git(root, 'init', '-q')
            git(root, 'config', 'user.name', 'Catalog Test')
            git(root, 'config', 'user.email', 'test@example.invalid')
            (root / 'README.md').write_text('fixture\n')
            git(root, 'add', '.')
            git(root, 'commit', '-qm', 'fixture')
        self.targets = [self.target('alpha'), self.target('previous', 'migration', True)]
        self.catalog = {'apiVersion': 'gitops.svc.plus/v1alpha1', 'kind': 'IaCTargetCatalog',
            'target_manifests': ['iac/targets/fixture.yaml'], 'migration_sources': []}
        self.publish()

    def target(self, name, status='active', persistent=False):
        identity = dict(environment='uat', project='example.net', provider='akamai-cloud', account='tenant-a', namespace=name)
        prefix = 'resources' if status == 'active' else 'iac/migrations/resources'
        return dict(id='uat-' + name, **identity, workspace=name,
            lifecycle=dict(status=status, persistent=persistent), provenance=dict(commit="a"*40,path="historical/resources.yaml"), auth=dict(expected_identity='tenant-a'),
            stages=dict(bootstrap=dict(mode='verify'), account=dict(mode='not_applicable', reason='No account resources'),
                resources=dict(mode='terraform', manifest=f'{prefix}/example.net/uat/akamai/{name}.yaml',
                    state=dict(key=canonical_state_key(**identity), cli_workspace='default'),
                    owners=['module.compute_' + name], protected=[], destroy_allowed=True, ownership_reviewed=True)))

    def publish(self):
        self.write('iac/catalog.yaml', self.catalog)
        self.write('iac/targets/fixture.yaml', {'apiVersion': 'gitops.svc.plus/v1alpha1', 'kind': 'IaCPipelineTargets', 'targets': self.targets})
        for target in self.targets:
            glob = {k: target[k] for k in ('provider', 'environment', 'project', 'account', 'workspace')}
            glob['state_namespace'] = target['namespace']
            self.write(target['stages']['resources']['manifest'], {'global': glob,
                'ssh_keys': [{'public': 'fixture-public-key'}], 'hosts': [{'name': target['namespace'], 'type': 'fixture'}]})
        git(self.root, 'add', '.')
        git(self.root, 'commit', '--allow-empty', '-qm', 'declarations')

    def write(self, path, doc):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc, sort_keys=False))

    def load(self, **kwargs):
        return load_targets(self.root, 'iac/catalog.yaml', environment='uat', provider='akamai-cloud', account='tenant-a', **kwargs)

    def context(self, manifest='iac/catalog.yaml', action='plan', selectors=None):
        return prepare(self.root, self.iac, manifest, 'uat', action, 'resources', 'verify', 'test', {}, selectors=selectors)

    def test_catalog_add_remove_and_namespace_migration_select_same_states(self):
        self.assertEqual([t['namespace'] for t in self.load()[0]], ['alpha'])
        self.assertEqual([t['namespace'] for t in self.load(include_migrations=True)[0]], ['alpha', 'previous'])
        self.targets.append(self.target('new-domain'))
        self.publish()
        context = self.context()
        self.assertEqual([t['namespace'] for t in context['targets']], ['alpha', 'new-domain'])
        targets, sources, _ = PREFLIGHT.load_preflight_targets(self.root, 'iac/catalog.yaml', 'uat', 'tenant-a')
        self.assertEqual([t['namespace'] for t in targets], ['alpha', 'previous', 'new-domain'])
        self.targets[0]['lifecycle']['status'] = 'migration'
        self.targets[0]['stages']['resources']['manifest'] = 'iac/migrations/resources/example.net/uat/akamai/alpha.yaml'
        self.publish()
        self.assertEqual([t['namespace'] for t in self.load()[0]], ['new-domain'])
        self.assertEqual(targets[0]['stages']['resources']['state']['key'], self.targets[0]['stages']['resources']['state']['key'])

    def test_migration_direct_execution_and_persistent_destroy_are_blocked(self):
        self.assertRaises(ContractError, self.context, action='destroy', selectors={'workspace':'previous'})
        self.targets[0]['lifecycle']['persistent'] = True
        self.publish()
        with self.assertRaisesRegex(ContractError, 'persistent lifecycle'):
            self.context(action='destroy')
        self.assertEqual(len(self.context(action='check')['targets']), 2)

    def test_duplicate_keys_alias_mismatch_and_resource_identity_fail_before_io(self):
        changes = [lambda t: t.update(namespace='different'),
                   lambda t: t['stages']['resources']['state'].update(key='terraform/prod/wrong.tfstate'),
                   lambda t: t.update(account='other-account')]
        for change in changes:
            original = copy.deepcopy(self.targets)
            change(self.targets[0]); self.publish()
            with self.assertRaises((ContractError, ValueError)): self.load()
            self.targets = original; self.publish()
        duplicate = copy.deepcopy(self.targets[0]); duplicate['id'] = 'alias'
        self.targets.append(duplicate); self.publish()
        with self.assertRaisesRegex(ContractError, 'duplicate state'): self.load()

    def test_reference_escape_and_tamper_are_rejected(self):
        self.catalog['target_manifests'] = ['../outside.yaml']; self.publish()
        with self.assertRaises(ContractError): self.load()
        self.catalog['target_manifests'] = ['iac/targets/fixture.yaml']; self.publish()
        context = self.context()
        self.targets[0]['lifecycle']['persistent'] = True; self.publish()
        with self.assertRaises(ContractError): revalidate(context, self.root, self.iac)

    def test_preflight_uses_declared_keys_checks_identity_and_keeps_migration_read_only(self):
        keys = []
        def inspect(key, env):
            keys.append(key)
            return dict(state_key=key, present=False, resources=[], protected_text=False)
        args = SimpleNamespace(gitops_root=str(self.root), iac_root=str(ROOT), catalog='iac/catalog.yaml',
            environment='uat', account='tenant-a', correlation_id='fixture')
        with patch.object(PREFLIGHT, 'inspect_terraform_state', side_effect=inspect), \
             patch.object(PREFLIGHT, 'linode_get_pages', return_value=[]), \
             patch.object(PREFLIGHT, 'verify_identity') as identity, \
             patch.dict(os.environ, LINODE_TOKEN='fixture'):
            report = PREFLIGHT.run(args)
        self.assertEqual(keys, [t['stages']['resources']['state']['key'] for t in self.targets])
        self.assertEqual(identity.call_count, 1)
        old = report['namespaces'][1]
        self.assertEqual(old['lifecycle']['status'], 'migration')
        self.assertEqual(old['state_binding_count'], 0)
        self.assertFalse(old['cleanup_eligible'])
        self.assertNotIn('plan-create', old['recommendation'])
        with patch.object(PREFLIGHT, 'verify_identity', side_effect=ContractError('wrong account')), \
             patch.object(PREFLIGHT, 'inspect_terraform_state') as state, patch.dict(os.environ, LINODE_TOKEN='fixture'):
            with self.assertRaises(ContractError): PREFLIGHT.run(args)
            state.assert_not_called()

    def test_migration_never_suggests_importing_a_live_replacement(self):
        targets, _, _ = PREFLIGHT.load_preflight_targets(self.root, 'iac/catalog.yaml', 'uat', 'tenant-a')
        expected = PREFLIGHT.load_manifest_expectations(self.root, ROOT, targets)[1]
        row = PREFLIGHT._classify_namespace(expected, [{'id':'99','label':'previous'}], [], [], [])
        self.assertEqual(row['recommendation'], 'retain-for-reviewed-state-handoff')
        self.assertFalse(row['cleanup_eligible'])
        state = [{'address':'module.compute_previous.linode_instance.this','resource_type':'linode_instance','id':'99','label':'renamed'}]
        row = PREFLIGHT._classify_namespace(expected, [{'id':'99','label':'previous'}], [], [], state)
        self.assertEqual(row['status'], 'ambiguous')
        self.assertEqual(row['state_binding_count'], 1)

    def test_legacy_catalog_selectors_cannot_expand_deployment_scope(self):
        output = Path(self.tmp.name) / 'outputs'
        values = dict(action='plan', environment='uat', cloud_provider='akamai-cloud', account='tenant-a', target_manifest='iac/catalog.yaml')
        env = dict(os.environ, IAC_ROOT=str(self.iac), IAC_GITOPS_ROOT=str(self.root), IAC_STAGE='resources', IAC_PROVIDER='akamai-cloud', IAC_INPUTS=json.dumps(values), GITHUB_OUTPUT=str(output))
        command = [sys.executable, str(ROOT / 'scripts/pipeline/unified_cli.py')]
        result = subprocess.run(command + ['normalize-legacy'], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        fields = dict(line.split('=', 1) for line in output.read_text().splitlines())
        self.assertEqual(fields['target_manifest'], 'iac/catalog.yaml')
        self.assertEqual(json.loads(fields['selectors'])['account'], 'tenant-a')
        env.update(IAC_MANIFEST='iac/catalog.yaml', IAC_ENVIRONMENT='uat', IAC_ACTION='plan', IAC_SCOPE='resources', IAC_REF='fixture', IAC_GITOPS_REF='fixture', IAC_NORMALIZED_SELECTORS=fields['selectors'], IAC_SELECTORS='{"account":"other-account"}', IAC_CONTRACT=str(Path(self.tmp.name)/'context.json'))
        result = subprocess.run(command + ['prepare'], env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('selectors conflict', result.stderr)
        self.assertFalse(Path(env['IAC_CONTRACT']).exists())

    def test_removing_or_renaming_a_domain_retains_old_state_for_inspection(self):
        before = Path(self.tmp.name) / 'before'
        shutil.copytree(self.root, before)
        self.targets = [self.target('replacement')]
        self.publish()
        with self.assertRaisesRegex(ContractError, 'state ownership removed'):
            validate_catalog_transition(before, self.root, 'iac/catalog.yaml')
        self.targets += [self.target('alpha', 'migration'), self.target('previous', 'retired', True)]
        self.publish()
        self.assertEqual(validate_catalog_transition(before, self.root, 'iac/catalog.yaml'), 2)

    def test_historical_source_provenance_and_exact_key_required(self):
        self.catalog['migration_sources'] = [dict(id='old-shared', environment='uat', project='historical',
            provider='akamai-cloud', account='tenant-a', namespace='selfhost', lifecycle=dict(status='migration',persistent=True),
            read_only=True, state=dict(key='terraform/uat/historical/akamai-cloud/tenant-a/selfhost/terraform.tfstate',cli_workspace='default'),
            provenance=dict(commit='a'*40,path='old/workflow.yaml'))]
        self.publish()
        self.assertEqual(len(self.load()[1]), 1)
        self.catalog['migration_sources'][0]['read_only'] = False; self.publish()
        with self.assertRaisesRegex(ContractError, 'read-only migration'): self.load()

if __name__ == '__main__': unittest.main()
