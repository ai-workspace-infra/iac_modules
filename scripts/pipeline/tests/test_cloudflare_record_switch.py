import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'cloudflare-record-switch.py'
spec = importlib.util.spec_from_file_location('record_switch', MODULE)
switch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(switch)


class Client:
    def __init__(self):
        self.rows = {
            'api.example.test': [{'id': 'api', 'name': 'api.example.test', 'type': 'CNAME', 'content': 'old.example.test', 'ttl': 300, 'proxied': False}],
            'example.test': [
                {'id': 'web', 'name': 'example.test', 'type': 'A', 'content': '8.8.8.8', 'ttl': 60, 'proxied': False},
                {'id': 'mail', 'name': 'example.test', 'type': 'MX', 'content': 'mail.example.test', 'ttl': 3600, 'proxied': False},
            ],
        }
        self.writes = []
        self.fail_reply = False

    def zone_id(self, zone):
        return 'zone'

    def records(self, zone, name):
        return copy.deepcopy(self.rows[name])

    def update(self, zone, record_id, payload):
        self.writes.append(record_id)
        for rows in self.rows.values():
            for row in rows:
                if row['id'] == record_id:
                    row.update(payload)
        if self.fail_reply:
            self.fail_reply = False
            raise switch.owner.OperationError('response lost')


class RecordSwitchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.checkpoint = Path(self.temp.name) / 'switch.json'
        self.client = Client()
        self.plan = {'environment': 'prod', 'records': [
            {'zone': 'example.test', 'name': 'api.example.test', 'type': 'CNAME', 'expected_content': 'old.example.test', 'content': 'new.example.test'},
            {'zone': 'example.test', 'name': 'example.test', 'type': 'A', 'expected_content': '8.8.8.8', 'content': '1.1.1.1'},
        ]}

    def test_preview_and_idempotent_switch_preserve_mail_and_flags(self):
        before_mail = copy.deepcopy(self.client.rows['example.test'][1])
        switch.execute(self.plan, self.client, self.checkpoint)
        self.assertEqual(self.client.writes, [])
        self.assertFalse(self.checkpoint.exists())
        switch.execute(self.plan, self.client, self.checkpoint, apply=True)
        switch.execute(self.plan, self.client, self.checkpoint, apply=True)
        self.assertEqual(self.client.writes, ['api', 'web'])
        self.assertEqual(self.client.rows['example.test'][1], before_mail)
        self.assertEqual(self.client.rows['api.example.test'][0]['ttl'], 300)
        self.assertFalse(self.client.rows['api.example.test'][0]['proxied'])

    def test_uncertain_reply_reconciles_before_resuming(self):
        self.client.fail_reply = True
        with self.assertRaises(switch.owner.OperationError):
            switch.execute(self.plan, self.client, self.checkpoint, apply=True)
        self.assertTrue(self.checkpoint.exists())
        switch.execute(self.plan, self.client, self.checkpoint, apply=True)
        self.assertEqual(self.client.writes, ['api', 'web'])

    def test_all_records_preflight_before_first_mutation(self):
        self.client.rows['example.test'][0]['content'] = '9.9.9.9'
        with self.assertRaises(switch.owner.OperationError):
            switch.execute(self.plan, self.client, self.checkpoint, apply=True)
        self.assertEqual(self.client.writes, [])

    def test_concurrent_provider_change_and_plan_change_stop(self):
        switch.execute(self.plan, self.client, self.checkpoint, apply=True)
        self.client.rows['api.example.test'][0]['content'] = 'other.example.test'
        with self.assertRaises(switch.owner.OperationError):
            switch.execute(self.plan, self.client, self.checkpoint, apply=True)
        self.plan['records'][0]['content'] = 'another.example.test'
        with self.assertRaises(switch.owner.OperationError):
            switch.execute(self.plan, self.client, self.checkpoint, apply=True)
        self.assertEqual(self.client.writes, ['api', 'web'])


if __name__ == '__main__':
    unittest.main()
