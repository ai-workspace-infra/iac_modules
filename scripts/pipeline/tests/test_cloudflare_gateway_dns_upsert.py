import copy
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gateway", ROOT / "cloudflare-gateway-dns-upsert.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class FakeCloudflare:
    def __init__(self, records=None):
        self.current = copy.deepcopy(records or [])
        self.updates = []
        self.creates = []
        self.deletes = []

    def zone_id(self, zone):
        return "zone"

    def records(self, zone, name):
        return copy.deepcopy(self.current)

    def create(self, zone, payload):
        record = dict(payload, id="created")
        self.current.append(record)
        self.creates.append(copy.deepcopy(payload))
        return record

    def update(self, zone, record_id, payload):
        self.updates.append(copy.deepcopy(payload))
        for record in self.current:
            if record["id"] == record_id:
                record.update(payload)
                return record
        raise AssertionError("missing record")

    def delete(self, zone, record_id):
        self.deletes.append(record_id)
        self.current = [record for record in self.current if record["id"] != record_id]


class GatewayDNSUpsertTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = {
            "DNS_ENVIRONMENT": "uat", "CLOUDFLARE_ACCOUNT_ID": "a" * 32,
            "DNS_ZONE": "svc.plus", "DNS_RECORD_NAME": "tw-xconnect.svc.plus",
            "DNS_TARGET_IP": "93.184.216.35", "DNS_CHECKPOINT_PATH": str(Path(self.temp.name) / "checkpoint.json"),
            "DNS_WAIT_FOR_RESOLVER": "true",
        }
        self.config = module.Config.from_env(self.env)

    def record(self, content="93.184.216.34", record_id="existing"):
        return [{"id": record_id, "type": "A", "name": self.env["DNS_RECORD_NAME"], "content": content,
                 "ttl": 300, "proxied": False, "comment": "keep", "tags": ["owner:gateway"]}]

    def test_create_requires_absence_and_retains_recovery_point(self):
        client = FakeCloudflare()
        result = module.execute(self.config, client, waiter=lambda *_: True)
        self.assertEqual("create", result["action"])
        self.assertEqual(["created"], [record["id"] for record in client.current])
        self.assertEqual(0o600, os.stat(self.config.checkpoint).st_mode & 0o777)
        self.assertEqual("created", result["record_id"])

    def test_update_preserves_attributes_in_checkpoint(self):
        client = FakeCloudflare(self.record())
        result = module.execute(self.config, client, waiter=lambda *_: True)
        self.assertEqual("update", result["action"])
        self.assertEqual("keep", module.load_checkpoint(self.config)["original"]["comment"])
        self.assertEqual("93.184.216.35", client.current[0]["content"])

    def test_noop_does_not_write(self):
        records = self.record("93.184.216.35")
        records[0]["ttl"] = 60
        client = FakeCloudflare(records)
        result = module.execute(self.config, client, waiter=lambda *_: True)
        self.assertEqual("noop", result["action"])
        self.assertFalse(client.updates or client.creates or client.deletes)

    def test_conflicts_fail_closed_without_deletion(self):
        for records in [self.record() + self.record(record_id="second"),
                        [dict(self.record()[0], type="CNAME")]]:
            client = FakeCloudflare(records)
            with self.assertRaises(module.OperationError):
                module.execute(self.config, client, waiter=lambda *_: True)
            self.assertFalse(client.updates or client.creates or client.deletes)

    def test_resolver_failure_restores_update(self):
        client = FakeCloudflare(self.record())
        with self.assertRaisesRegex(module.OperationError, "previous DNS state restored"):
            module.execute(self.config, client, waiter=lambda *_: False)
        self.assertEqual("93.184.216.34", client.current[0]["content"])
        self.assertEqual(2, len(client.updates))

    def test_resolver_failure_removes_only_exact_created_record(self):
        client = FakeCloudflare()
        with self.assertRaisesRegex(module.OperationError, "previous DNS state restored"):
            module.execute(self.config, client, waiter=lambda *_: False)
        self.assertFalse(client.current)
        self.assertEqual(["created"], client.deletes)

    def test_retry_after_create_is_idempotent(self):
        client = FakeCloudflare()
        first = module.execute(self.config, client, waiter=lambda *_: True)
        checkpoint = self.config.checkpoint.read_bytes()
        second = module.execute(self.config, client, waiter=lambda *_: True)
        self.assertEqual("create", first["action"])
        self.assertEqual("noop", second["action"])
        self.assertEqual(checkpoint, self.config.checkpoint.read_bytes())
        self.assertEqual(1, len(client.creates))

    def test_retry_after_update_is_idempotent(self):
        client = FakeCloudflare(self.record())
        first = module.execute(self.config, client, waiter=lambda *_: True)
        second = module.execute(self.config, client, waiter=lambda *_: True)
        self.assertEqual("update", first["action"])
        self.assertEqual("noop", second["action"])
        self.assertEqual(1, len(client.updates))

    def test_cross_environment_checkpoint_and_bad_input_rejected(self):
        module.execute(self.config, FakeCloudflare(), waiter=lambda *_: True)
        prod = dict(self.env, DNS_ENVIRONMENT="prod")
        with self.assertRaises(module.OperationError):
            module.execute(module.Config.from_env(prod), FakeCloudflare(), waiter=lambda *_: True)
        for name, value in [("DNS_TARGET_IP", "10.0.0.1"), ("DNS_RECORD_NAME", "other.invalid"),
                            ("CLOUDFLARE_ACCOUNT_ID", "bad")]:
            with self.subTest(name=name), self.assertRaises(module.OperationError):
                module.Config.from_env(dict(self.env, **{name: value}))


if __name__ == "__main__":
    unittest.main()
