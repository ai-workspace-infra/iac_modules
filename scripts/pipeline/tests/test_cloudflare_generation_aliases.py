import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml

path = Path(__file__).resolve().parents[1] / 'cloudflare-generation-aliases.py'
spec = importlib.util.spec_from_file_location('generation_aliases', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GenerationAliases(unittest.TestCase):
    def test_provider_empty_settings_do_not_falsely_indicate_drift(self):
        record = {'type': 'A', 'name': 'console-selfhost-prod-v4.svc.plus', 'content': '35.229.188.193',
                  'ttl': 60, 'proxied': False}
        self.assertEqual(module.owner.record_payload(record), module.owner.record_payload(dict(record, settings={})))

    def test_plan_cannot_include_shared_public_names(self):
        rows = module.plan('prod-v10', '35.229.188.193')
        self.assertEqual(len(rows), 4)
        self.assertTrue(all('-selfhost-prod-v10.svc.plus' in row['name'] for row in rows))
        for invalid in ['prod', 'v4', 'prod-v0', 'prod-v4.svc.plus', 'prod-v4\n']:
            with self.assertRaises(module.owner.OperationError):
                module.plan(invalid, '35.229.188.193')

    def test_conflict_stops_before_any_write(self):
        class Client:
            account_id = 'fixture'
            def zone_id(self, zone):
                return 'fixture-zone'
            def records(self, zone, name):
                return [{'type': 'CNAME', 'content': 'unexpected.example'}] if name.startswith('billing-') else []
        with self.assertRaises(module.owner.OperationError):
            module.run(Client(), 'prod-v4', '35.229.188.193', Path('/not-used'), True)

    def test_preview_reports_only_four_exact_names_and_existing_actions(self):
        class Client:
            def __init__(self):
                self.queried = []
                self.updated = []
            def zone_id(self, zone):
                self.assert_zone = zone
                return 'fixture-zone'
            def records(self, zone, name):
                self.queried.append(name)
                return [{
                    'id': name.split('.')[0], 'type': 'A', 'name': name,
                    'content': '35.229.188.193', 'ttl': 300, 'proxied': False,
                    'comment': '', 'tags': [],
                }]
        client = Client()
        result = module.run(client, 'prod-v5', '104.64.208.209', Path('/unused'), False)
        expected = [f'{service}-selfhost-prod-v5.svc.plus'
                    for service in ('console', 'accounts', 'billing', 'postgresql')]
        self.assertEqual(client.queried, expected)
        self.assertEqual([row['name'] for row in result['records']], expected)
        self.assertEqual({row['action'] for row in result['records']}, {'update'})
        self.assertTrue(all(row['address'] == '104.64.208.209' for row in result['records']))
        self.assertFalse(result['public_aliases_modified'])

    def test_apply_dispatches_only_the_four_rendered_records(self):
        class Client:
            account_id = 'fixture-account'
            def zone_id(self, zone):
                return 'fixture-zone'
            def records(self, zone, name):
                return []
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / 'checkpoints'
            with mock.patch.object(module.owner, 'execute', side_effect=lambda config, client: {
                'changed': True, 'action': 'create', 'record_id': config.name, 'address': config.target,
            }) as execute:
                result = module.run(Client(), 'prod-v5', '104.64.208.209', checkpoint, True)
        expected = [f'{service}-selfhost-prod-v5.svc.plus'
                    for service in ('console', 'accounts', 'billing', 'postgresql')]
        self.assertEqual([call.args[0].name for call in execute.call_args_list], expected)
        self.assertEqual([row['name'] for row in result['records']], expected)
        self.assertFalse(result['public_aliases_modified'])

    def test_gitops_and_cmdb_render_exact_generation_aliases(self):
        declaration = {
            'global': {'provider': 'akamai-cloud', 'environment': 'prod', 'project': 'svc.plus'},
            'hosts': [{
                'name': 'web-saas-prod-v5',
                'host_vars': {
                    'target_generation': 'prod-v5',
                    'service_domains': [
                        f'{service}-selfhost-prod-v5.svc.plus'
                        for service in ('console', 'accounts', 'billing', 'postgresql')
                    ],
                },
            }],
        }
        cmdb = {
            declaration['hosts'][0]['host_vars']['service_domains'][0]: {
                'name': 'web-saas-prod-v5',
                'fqdn': declaration['hosts'][0]['host_vars']['service_domains'][0],
                'ip': '104.64.208.209',
                'instance_id': 'fixture-instance',
                'host_vars': declaration['hosts'][0]['host_vars'],
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            resources = Path(directory) / 'resource.yaml'
            cmdb_path = Path(directory) / 'cmdb.json'
            resources.write_text(yaml.safe_dump(declaration), encoding='utf-8')
            cmdb_path.write_text(json.dumps(cmdb), encoding='utf-8')
            rendered = module.render_sources(resources, cmdb_path)
        self.assertEqual(rendered['generation'], 'prod-v5')
        self.assertEqual(rendered['address'], '104.64.208.209')
        self.assertEqual(len(rendered['records']), 4)
        self.assertEqual(
            [row['name'] for row in rendered['records']],
            declaration['hosts'][0]['host_vars']['service_domains'],
        )
        self.assertIsNotNone(rendered['source_sha256']['gitops'])
        self.assertIsNotNone(rendered['source_sha256']['cmdb'])

    def test_gitops_cmdb_drift_or_non_generation_domain_fails_closed(self):
        services = ('console', 'accounts', 'billing', 'postgresql')
        domains = [f'{service}-selfhost-prod-v5.svc.plus' for service in services]
        declaration = {
            'global': {'provider': 'akamai-cloud', 'environment': 'prod', 'project': 'svc.plus'},
            'hosts': [{'name': 'web-saas-prod-v5', 'host_vars': {
                'target_generation': 'prod-v5', 'service_domains': domains,
            }}],
        }
        cmdb = {domains[0]: {
            'name': 'web-saas-prod-v5', 'fqdn': domains[0], 'ip': '104.64.208.209',
            'instance_id': 'fixture-instance', 'host_vars': {
                'target_generation': 'prod-v5', 'service_domains': domains,
            },
        }}
        with tempfile.TemporaryDirectory() as directory:
            resources = Path(directory) / 'resource.yaml'
            cmdb_path = Path(directory) / 'cmdb.json'
            resources.write_text(yaml.safe_dump(declaration), encoding='utf-8')
            cmdb_path.write_text(json.dumps(cmdb), encoding='utf-8')
            cmdb[domains[0]]['host_vars']['target_generation'] = 'prod-v4'
            cmdb_path.write_text(json.dumps(cmdb), encoding='utf-8')
            with self.assertRaisesRegex(module.owner.OperationError, 'generations differ'):
                module.render_sources(resources, cmdb_path)

            cmdb[domains[0]]['host_vars']['target_generation'] = 'prod-v5'
            declaration['hosts'][0]['host_vars']['service_domains'][0] = 'console.svc.plus'
            resources.write_text(yaml.safe_dump(declaration), encoding='utf-8')
            with self.assertRaisesRegex(module.owner.OperationError, 'do not match'):
                module.render_sources(resources, cmdb_path)


if __name__ == '__main__':
    unittest.main()
