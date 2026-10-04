import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "cloudflare-dns-record.py"
SPEC = importlib.util.spec_from_file_location("cloudflare_dns_record", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeCloudflare:
    def __init__(self):
        self.current = {
            "id": "record", "name": "metrics.example.invalid", "type": "A",
            "content": "203.0.113.1", "ttl": 300, "proxied": False,
            "comment": "operator comment", "tags": ["owner:platform"],
            "settings": {},
        }
        self.updates = []

    def zone_id(self, zone):
        return "zone"

    def record(self, zone_id, name):
        return copy.deepcopy(self.current)

    def update(self, zone_id, record_id, payload):
        self.updates.append(copy.deepcopy(payload))
        self.current = dict(payload, id=record_id)


class DnsRecordTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.env = {
            "DNS_ENVIRONMENT": "uat", "DNS_ZONE": "example.invalid",
            "DNS_RECORD_NAME": "metrics.example.invalid", "DNS_ACTION": "cutover",
            "SOURCE_IP": "203.0.113.1", "TARGET_IP": "203.0.113.2",
            "DNS_CHECKPOINT_PATH": str(Path(self.temporary.name) / "checkpoint.json"),
        }
        self.config = MODULE.Config.from_env(self.env)
        self.client = FakeCloudflare()
        self.original = copy.deepcopy(self.client.current)

    def execute(self, config=None, waiter=None):
        return MODULE.execute(config or self.config, self.client, waiter or (lambda *_: True))

    def test_cutover_then_service_failure_restores_all_record_attributes(self):
        self.execute()
        checkpoint = json.loads(self.config.checkpoint.read_text())
        self.assertEqual(os.stat(self.config.checkpoint).st_mode & 0o777, 0o600)
        self.assertEqual(checkpoint["original"]["comment"], "operator comment")
        self.env["DNS_ACTION"] = "restore"
        self.execute(MODULE.Config.from_env(self.env))
        self.assertEqual(self.client.current, self.original)
        self.assertEqual(len(self.client.updates), 2)

    def test_provider_convergence_failure_restores_original_and_fails(self):
        with self.assertRaisesRegex(MODULE.OperationError, "original DNS state restored"):
            self.execute(waiter=lambda _, address: address == self.env["SOURCE_IP"])
        self.assertEqual(self.client.current, self.original)

    def test_retry_preserves_the_original_recovery_point(self):
        self.execute()
        before = self.config.checkpoint.read_bytes()
        self.execute()
        self.assertEqual(self.config.checkpoint.read_bytes(), before)
        self.assertEqual(len(self.client.updates), 1)
        self.env["DNS_ACTION"] = "restore"
        self.execute(MODULE.Config.from_env(self.env))
        self.assertEqual(self.client.current, self.original)

    def test_already_desired_record_is_never_mutated_by_failed_service_recovery(self):
        self.client.current.update(content=self.env["TARGET_IP"], ttl=60)
        desired = copy.deepcopy(self.client.current)
        self.execute()
        self.env["DNS_ACTION"] = "restore"
        self.execute(MODULE.Config.from_env(self.env))
        self.assertEqual(self.client.current, desired)
        self.assertFalse(self.client.updates)

    def test_unexpected_current_address_prevents_a_write(self):
        self.client.current["content"] = "203.0.113.3"
        with self.assertRaisesRegex(MODULE.OperationError, "expected address"):
            self.execute()
        self.assertFalse(self.client.updates)
        self.assertFalse(self.config.checkpoint.exists())

    def test_restore_refuses_concurrent_record_changes(self):
        self.execute()
        self.client.current["comment"] = "changed by another operator"
        self.env["DNS_ACTION"] = "restore"
        with self.assertRaisesRegex(MODULE.OperationError, "changed after this operation"):
            self.execute(MODULE.Config.from_env(self.env))
        self.assertEqual(len(self.client.updates), 1)

    def test_cross_environment_checkpoint_is_rejected(self):
        self.execute()
        self.env.update(DNS_ACTION="restore", DNS_ENVIRONMENT="prod")
        with self.assertRaisesRegex(MODULE.OperationError, "environment or target mismatch"):
            self.execute(MODULE.Config.from_env(self.env))
        self.assertEqual(len(self.client.updates), 1)

    def test_explicit_rollback_is_retained_when_propagation_fails(self):
        self.client.current["content"] = self.env["TARGET_IP"]
        self.env["DNS_ACTION"] = "rollback"
        with self.assertRaisesRegex(MODULE.OperationError, "convergence timed out"):
            self.execute(MODULE.Config.from_env(self.env), waiter=lambda *_: False)
        self.assertEqual(self.client.current["content"], self.env["SOURCE_IP"])
        self.assertEqual(len(self.client.updates), 1)

    def test_missing_or_invalid_targets_fail_before_provider_access(self):
        for key, value in (("DNS_RECORD_NAME", ""), ("SOURCE_IP", "not-an-ip"),
                           ("TARGET_IP", self.env["SOURCE_IP"]),
                           ("DNS_ACTION", "delete"), ("DNS_ZONE", "other.invalid")):
            env = dict(self.env)
            env[key] = value
            with self.subTest(key=key), self.assertRaises((MODULE.OperationError, ValueError)):
                MODULE.Config.from_env(env)
        self.assertFalse(self.client.updates)


class ProviderResponseTests(unittest.TestCase):
    def test_record_ambiguity_is_rejected(self):
        client = MODULE.Cloudflare("synthetic-test-token")
        record = FakeCloudflare().current
        client.request = lambda *_: [record, record]
        with self.assertRaisesRegex(MODULE.OperationError, "exactly one A record"):
            client.record("zone", record["name"])


if __name__ == "__main__":
    unittest.main()
