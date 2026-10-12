import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('api_alias_owner', ROOT / 'cloudflare-api-aliases.py')
owner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owner)
REVISION = 'a' * 40


def config():
    boundaries = [
        {'id': 'auth', 'worker_name': 'edge-gateway-auth-prod', 'routes': ['/api/auth/*']},
        {'id': 'admin', 'worker_name': 'edge-gateway-admin-prod', 'routes': ['/api/admin/*']},
        {'id': 'core', 'worker_name': 'edge-gateway-core-prod', 'routes': ['/api/*']},
    ]
    domains = {key + '.svc.plus': {'serverless': key + '-serverless-prod.svc.plus', 'selfhost': key + '-selfhost-prod.svc.plus'} for key in ('accounts', 'billing')}
    return {'kind': 'EdgeRoutingConfig', 'metadata': {'environment': 'prod'}, 'spec': {
        'runtime': {'mode': 'serverless', 'routing': {'dns': {'api_alias_mode': 'worker-routes-cname',
            'api_cname_records': domains, 'canonical_records': {k: v['serverless'] for k, v in domains.items()}}}},
        'domains': domains,
        'serverless': {'accounts_host': 'accounts-serverless-prod.svc.plus', 'billing_host': 'billing-serverless-prod.svc.plus',
            'edge_gateway': {'boundaries': boundaries, 'defaults': {'primary_upstream': 'https://accounts-selfhost-prod.svc.plus',
                'fallback_upstream': 'https://accounts.run.app', 'billing_primary_upstream': 'https://billing-selfhost-prod.svc.plus',
                'billing_fallback_upstream': 'https://billing.run.app'}}},
    }}


class FakeCloudflare:
    def __init__(self, cfg):
        self.account_id = 'b' * 32
        self.cfg = cfg
        self.writes = []
        self.failure = None
        self.dns = {}
        self.domains = []
        for host in ('accounts.svc.plus', 'accounts-serverless-prod.svc.plus', 'billing-serverless-prod.svc.plus'):
            self.attach({'hostname': host, 'service': 'edge-gateway-core-prod', 'zone_id': 'zone'})
        self.dns['xworktech.com'] = [self.record('xworktech.com', 'A', '203.0.113.1')]
        self.dns['console.svc.plus'] = [self.record('console.svc.plus', 'CNAME', 'console.pages.dev')]
        self.writes.clear()

    def record(self, name, kind, content):
        return {'id': name, 'type': kind, 'name': name, 'content': content, 'ttl': 1, 'proxied': True}

    def attach(self, payload):
        item = dict(payload, id=payload['hostname'])
        self.domains = [d for d in self.domains if d['hostname'] != item['hostname']] + [item]
        self.dns[item['hostname']] = [self.record(item['hostname'], 'AAAA', '100::')]
        return copy.deepcopy(item)

    def request(self, method, path, payload=None):
        if method != 'GET': self.writes.append((method, path))
        if path.endswith('/settings'):
            defaults = self.cfg['spec']['serverless']['edge_gateway']['defaults']
            values = {'GATEWAY_REVISION': REVISION, 'RUNTIME_MODE': self.cfg['spec']['runtime']['mode'],
                **{k.upper(): v for k, v in defaults.items()}}
            return {'bindings': [{'name': k, 'type': 'plain_text', 'text': v} for k, v in values.items()]}
        if path.endswith('/workers/routes'):
            routes = [{'pattern': 'accounts.svc.plus' + route, 'script': b['worker_name']}
                for b in self.cfg['spec']['serverless']['edge_gateway']['boundaries'] for route in b['routes']]
            return routes + [{'pattern': 'billing.svc.plus/*', 'script': 'edge-gateway-core-prod'}]
        if path.endswith('/workers/domains'):
            return copy.deepcopy(self.domains) if method == 'GET' else self.attach(payload)
        if method == 'DELETE' and '/workers/domains/' in path:
            identity = path.rsplit('/', 1)[1]
            self.domains = [d for d in self.domains if d['id'] != identity]
            self.dns.pop(identity, None)
            return None
        raise AssertionError((method, path))

    def zone_id(self, zone): return 'zone'
    def records(self, zone, name): return copy.deepcopy(self.dns.get(name, []))
    def delete(self, zone, identity):
        self.writes.append(('delete', identity))
        for name in list(self.dns): self.dns[name] = [r for r in self.dns[name] if r['id'] != identity]
    def create(self, zone, payload):
        self.writes.append(('create', payload['name']))
        if self.failure == payload['name']:
            self.failure = None
            raise owner.OperationError('simulated provider failure')
        item = dict(payload, id=payload['name'])
        self.dns.setdefault(payload['name'], []).append(item)
        return copy.deepcopy(item)
    def update(self, zone, identity, payload):
        self.delete(zone, identity)
        return self.create(zone, payload)


class APITests(unittest.TestCase):
    def run_owner(self, cfg, client, revision=REVISION):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'checkpoint.json'
            result = owner.reconcile(client, cfg, revision, path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            return result

    def test_two_aliases_and_unrelated_entries_preserved(self):
        cfg = config(); client = FakeCloudflare(cfg)
        before = copy.deepcopy({k: client.dns[k] for k in ('xworktech.com', 'console.svc.plus')})
        result = self.run_owner(cfg, client)
        self.assertTrue(result['provider_verified'])
        self.assertFalse(result['business_verified'])
        for name, target in result['aliases'].items():
            self.assertEqual(client.dns[name][0]['content'], target)
            self.assertEqual(client.dns[name][0]['type'], 'CNAME')
        self.assertEqual(before, {k: client.dns[k] for k in before})

    def test_idempotent_no_mutations(self):
        cfg = config(); client = FakeCloudflare(cfg)
        self.run_owner(cfg, client); client.writes.clear()
        self.run_owner(cfg, client)
        self.assertEqual(client.writes, [])

    def test_provider_failure_restores_first_domain(self):
        cfg = config(); client = FakeCloudflare(cfg)
        before = copy.deepcopy(client.dns)
        client.failure = 'billing.svc.plus'
        with self.assertRaises(owner.OperationError): self.run_owner(cfg, client)
        self.assertEqual(before, client.dns)
        self.assertIsNotNone(owner.domain_for(client.domains, 'accounts.svc.plus'))

    def test_wrong_revision_blocks_before_writes(self):
        cfg = config(); client = FakeCloudflare(cfg)
        with self.assertRaises(owner.OperationError): self.run_owner(cfg, client, 'c' * 40)
        self.assertEqual(client.writes, [])

    def test_unrelated_canonical_record_blocks_before_writes(self):
        cfg = config(); client = FakeCloudflare(cfg)
        client.dns['billing.svc.plus'] = [client.record('billing.svc.plus', 'A', '203.0.113.2')]
        with self.assertRaises(owner.OperationError): self.run_owner(cfg, client)
        self.assertEqual(client.writes, [])

    def test_foreign_worker_domain_blocks_before_writes(self):
        cfg = config(); client = FakeCloudflare(cfg)
        owner.domain_for(client.domains, 'accounts.svc.plus')['service'] = 'unrelated-worker'
        with self.assertRaises(owner.OperationError): self.run_owner(cfg, client)
        self.assertEqual(client.writes, [])

    def test_selfhost_origin_worker_loop_rejected(self):
        cfg = config(); cfg['spec']['runtime']['mode'] = 'selfhost'
        for name, targets in cfg['spec']['runtime']['routing']['dns']['api_cname_records'].items():
            cfg['spec']['runtime']['routing']['dns']['canonical_records'][name] = targets['selfhost']
        client = FakeCloudflare(cfg)
        client.attach({'hostname': 'accounts-selfhost-prod.svc.plus', 'service': 'edge-gateway-core-prod', 'zone_id': 'zone'})
        client.writes.clear()
        with self.assertRaises(owner.OperationError): self.run_owner(cfg, client)
        self.assertEqual(client.writes, [])

    def test_legacy_contract_never_implicitly_migrates(self):
        cfg = config(); cfg['spec']['runtime']['routing']['dns'].pop('api_alias_mode')
        client = FakeCloudflare(cfg)
        self.assertIsNone(owner.contract(cfg))
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(owner.reconcile(client, cfg, '', Path(directory) / 'cp')['status'], 'legacy-declaration-unchanged')
        self.assertEqual(client.writes, [])


if __name__ == '__main__': unittest.main()
