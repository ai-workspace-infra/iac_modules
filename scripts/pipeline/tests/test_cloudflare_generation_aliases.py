import importlib.util
from pathlib import Path
import unittest

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


if __name__ == '__main__':
    unittest.main()
