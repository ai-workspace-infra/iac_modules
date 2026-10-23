import copy
import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("dns_reconcile", Path(__file__).resolve().parents[1] / "dns-reconcile.py")
DNS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DNS
SPEC.loader.exec_module(DNS)

ACCOUNT, ZONE, RECORD = "a" * 32, "b" * 32, "c" * 32


class Provider:
    def __init__(self):
        self.items = []
        self.writes = []
        self.account = ACCOUNT
        self.zone_name = "example.invalid"
        self.status = "active"
        self.fail_write = False
        self.lose_create_response = False
        self.after_write = None
        self.before_write = lambda: None

    def zone(self, zone_id):
        return {"id": ZONE, "name": self.zone_name, "status": self.status, "account": {"id": self.account}}

    def records(self, zone_id, name):
        return copy.deepcopy(self.items)

    def write(self, action, record_id, record):
        self.before_write()
        self.writes.append((action, record_id, copy.deepcopy(record)))
        if self.fail_write:
            raise DNS.OperationError("Simulated provider failure")
        self.items = [] if action == "delete" else [{**copy.deepcopy(record), "id": record_id}]
        if self.after_write:
            self.after_write(self.items)
        if action == "create" and self.lose_create_response:
            raise DNS.OperationError("Simulated lost response")
        return copy.deepcopy(self.items[0]) if self.items else {"id": record_id}

    def create(self, zone_id, record):
        return self.write("create", RECORD, record)

    def update(self, zone_id, record_id, record):
        return self.write("update", record_id, record)

    def delete(self, zone_id, record_id):
        return self.write("delete", record_id, None)


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.path = self.root / "checkpoint.json"
        self.client = Provider()
        self.intent = {"version": 1, "environment": "uat", "run_id": "1234",
                       "release_tag": "uat-daily-build-2026.10.05-r1", "account_id": ACCOUNT,
                       "zone_id": ZONE, "zone_name": "example.invalid", "owner_tag": "owner:gateway",
                       "record": {"name": "gateway.example.invalid", "type": "A", "content": "8.8.4.4",
                                  "ttl": 60, "proxied": False}, "expected_record_id": None}

    def existing(self, address="8.8.8.8"):
        self.client.items = [{**self.intent["record"], "id": RECORD, "content": address,
                              "ttl": 300, "comment": "preserve this", "tags": ["purpose:gateway"],
                              "settings": {"ipv4_only": False}}]
        self.intent["expected_record_id"] = RECORD

    def plan(self):
        return DNS.make_plan(self.intent, self.client)

    def apply(self, plan=None, waiter=lambda *_: True):
        return DNS.apply(plan or self.plan(), self.client, self.path, waiter)

    def restore(self, plan, waiter=lambda *_: True):
        return DNS.restore(plan, self.client, self.path, waiter)

    def test_plan_has_no_writes_or_checkpoint(self):
        plan = self.plan()
        self.assertIsNone(plan["before"])
        self.assertFalse(self.client.writes)
        self.assertFalse(self.path.exists())

    def test_create_checkpoint_before_write_verified_receipt_and_exact_restore(self):
        plan = self.plan()
        self.client.before_write = lambda: self.assertEqual(DNS.load(self.path)["phase"], "prepared")
        result = self.apply(plan)
        self.assertTrue(result["provider_verified"])
        self.assertTrue(result["resolver_verified"])
        self.assertFalse(result["host_acceptance"])
        self.assertEqual(result["run_id"], "1234")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.client.before_write = lambda: None
        restored = self.restore(plan)
        self.assertFalse(restored["resolver_verified"])
        self.assertEqual([write[0] for write in self.client.writes], ["create", "delete"])
        self.assertFalse(self.client.items)
        self.restore(plan)
        self.assertEqual(len(self.client.writes), 2)

    def test_update_preserves_complete_configuration_and_restores(self):
        self.existing()
        original = copy.deepcopy(self.client.items)
        plan = self.plan()
        self.apply(plan)
        for field in ("comment", "tags", "settings"):
            self.assertEqual(self.client.items[0][field], original[0][field])
        self.restore(plan)
        self.assertEqual(self.client.items, original)

    def test_reapply_is_idempotent_and_keeps_recovery_point(self):
        plan = self.plan()
        self.apply(plan)
        checkpoint_before = self.path.read_bytes()
        self.apply(plan)
        self.assertEqual(len(self.client.writes), 1)
        self.assertEqual(self.path.read_bytes(), checkpoint_before)

    def test_exact_noop_still_verifies_resolver(self):
        self.existing(self.intent["record"]["content"])
        self.client.items[0]["ttl"] = 60
        calls = []
        result = self.apply(waiter=lambda *args: calls.append(args) or True)
        self.assertFalse(result["changed"])
        self.assertTrue(calls)
        self.assertFalse(self.client.writes)

    def test_non_a_duplicate_and_other_owner_are_refused(self):
        self.existing()
        original = copy.deepcopy(self.client.items)
        cases = [[dict(original[0], type="CNAME")], original * 2,
                 [dict(original[0], tags=["owner:canonical"])]]
        for items in cases:
            self.client.items = items
            with self.subTest(items=items), self.assertRaises(DNS.OperationError):
                self.plan()
        self.assertFalse(self.client.writes)

    def test_expected_absence_or_record_id_must_match(self):
        self.existing()
        self.intent["expected_record_id"] = None
        with self.assertRaisesRegex(DNS.OperationError, "Expected record"):
            self.plan()
        self.intent["expected_record_id"] = "d" * 32
        with self.assertRaises(DNS.OperationError):
            self.plan()
        self.assertFalse(self.client.writes)

    def test_zone_account_status_binding_refused_before_write(self):
        for field, wrong in (("account", "d" * 32), ("zone_name", "other.invalid"), ("status", "pending")):
            client = Provider()
            setattr(client, field, wrong)
            with self.subTest(field=field), self.assertRaisesRegex(DNS.OperationError, "binding"):
                DNS.make_plan(self.intent, client)
            self.assertFalse(client.writes)

    def test_invalid_intents_refused(self):
        changes = [("environment", "prod"), ("environment", "sit"), ("account_id", "../../bad"),
                   ("release_tag", "../bad"), ("owner_tag", "other")]
        for field, wrong in changes:
            spec = copy.deepcopy(self.intent)
            spec[field] = wrong
            with self.subTest(field=field), self.assertRaises(DNS.OperationError):
                DNS.make_plan(spec, self.client)
        for field, wrong in (("content", "127.0.0.1"), ("ttl", 300), ("proxied", True),
                             ("type", "CNAME"), ("name", "other.invalid")):
            spec = copy.deepcopy(self.intent)
            spec["record"][field] = wrong
            with self.subTest(field=field), self.assertRaises(DNS.OperationError):
                DNS.make_plan(spec, self.client)
        with self.assertRaises(DNS.OperationError):
            DNS.make_plan(dict(self.intent, credentials="synthetic-token"), self.client)

    def test_plan_change_between_read_and_apply_refused(self):
        self.existing()
        plan = self.plan()
        self.client.items[0]["comment"] = "changed externally"
        with self.assertRaisesRegex(DNS.OperationError, "after planning"):
            self.apply(plan)
        self.assertFalse(self.client.writes)
        self.assertFalse(self.path.exists())

    def test_readback_mismatch_cannot_emit_success_or_overwrite_other_writer(self):
        plan = self.plan()
        self.client.after_write = lambda items: items[0].update(comment="another writer")
        with self.assertRaisesRegex(DNS.OperationError, "readback"):
            self.apply(plan)
        with self.assertRaisesRegex(DNS.OperationError, "concurrent"):
            self.restore(plan)
        self.assertEqual(len(self.client.writes), 1)

    def test_resolver_timeout_retains_checkpoint_for_exact_recovery(self):
        self.existing()
        original = copy.deepcopy(self.client.items)
        plan = self.plan()
        with self.assertRaisesRegex(DNS.OperationError, "convergence"):
            self.apply(plan, waiter=lambda *_: False)
        self.assertEqual(DNS.load(self.path)["phase"], "applied")
        self.restore(plan)
        self.assertEqual(self.client.items, original)

    def test_dns_change_during_resolver_wait_refused(self):
        plan = self.plan()
        def mutate(*_):
            self.client.items[0]["content"] = "9.9.9.9"
            return True
        with self.assertRaisesRegex(DNS.OperationError, "during resolver"):
            self.apply(plan, waiter=mutate)
        with self.assertRaises(DNS.OperationError):
            self.restore(plan)
        self.assertEqual(len(self.client.writes), 1)

    def test_restore_rejects_changed_id_and_full_state(self):
        for field, changed in (("id", "d" * 32), ("ttl", 120), ("comment", "foreign"),
                               ("tags", ["owner:foreign"]), ("settings", {"ipv4_only": True})):
            with self.subTest(field=field):
                self.path.unlink(missing_ok=True)
                self.client = Provider()
                plan = self.plan()
                self.apply(plan)
                self.client.items[0][field] = changed
                with self.assertRaises(DNS.OperationError):
                    self.restore(plan)
                self.assertEqual(len(self.client.writes), 1)

    def test_lost_create_response_never_adopts_or_deletes_unknown_id(self):
        plan = self.plan()
        self.client.lose_create_response = True
        with self.assertRaises(DNS.OperationError):
            self.apply(plan)
        self.assertIsNone(DNS.load(self.path)["record_id"])
        with self.assertRaisesRegex(DNS.OperationError, "uncertain"):
            self.apply(plan)
        with self.assertRaises(DNS.OperationError):
            self.restore(plan)
        self.assertEqual(len(self.client.writes), 1)

    def test_update_failure_before_write_retains_original(self):
        self.existing()
        original = copy.deepcopy(self.client.items)
        plan = self.plan()
        self.client.fail_write = True
        with self.assertRaises(DNS.OperationError):
            self.apply(plan)
        self.client.fail_write = False
        result = self.restore(plan)
        self.assertFalse(result["changed"])
        self.assertEqual(self.client.items, original)

    def test_checkpoint_from_other_release_or_run_refused(self):
        plan = self.plan()
        self.apply(plan)
        for field, wrong in (("release_tag", "other"), ("run_id", "999")):
            wrong_plan = copy.deepcopy(plan)
            wrong_plan["intent"][field] = wrong
            with self.subTest(field=field), self.assertRaisesRegex(DNS.OperationError, "binding"):
                self.restore(wrong_plan)
        self.assertEqual(len(self.client.writes), 1)

    def test_plan_metadata_tampering_refused(self):
        self.existing()
        plan = self.plan()
        plan["desired"]["tags"] = []
        with self.assertRaisesRegex(DNS.OperationError, "metadata"):
            self.apply(plan)
        self.assertFalse(self.client.writes)

    def test_symlink_or_public_directory_cannot_receive_checkpoint(self):
        target = self.root / "other"
        target.write_text("preserve")
        self.path.symlink_to(target)
        with self.assertRaisesRegex(DNS.OperationError, "symlinks"):
            self.apply()
        self.assertEqual(target.read_text(), "preserve")
        self.path.unlink()
        public = self.root / "public"
        public.mkdir(mode=0o755)
        with self.assertRaisesRegex(DNS.OperationError, "private"):
            DNS.apply(self.plan(), self.client, public / "checkpoint")
        self.assertFalse(self.client.writes)

    def test_restored_operation_cannot_be_reapplied(self):
        plan = self.plan()
        self.apply(plan)
        self.restore(plan)
        with self.assertRaisesRegex(DNS.OperationError, "new operation"):
            self.apply(plan)
        self.assertEqual(len(self.client.writes), 2)

    def test_checkpoint_lock_contention_prevents_write(self):
        plan = self.plan()
        with DNS.checkpoint_lock(self.path):
            with self.assertRaisesRegex(DNS.OperationError, "in progress"):
                self.apply(plan)
        self.assertFalse(self.client.writes)

    def test_real_cli_plan_apply_restore_private_files_without_credentials(self):
        spec = self.root / "intent.json"
        planned = self.root / "plan.json"
        first_receipt = self.root / "applied.json"
        restored_receipt = self.root / "restored.json"
        DNS.save(spec, self.intent)
        arguments = [
            ["plan", "--intent", str(spec), "--output", str(planned)],
            ["apply", "--plan", str(planned), "--checkpoint", str(self.path), "--receipt", str(first_receipt)],
            ["restore", "--plan", str(planned), "--checkpoint", str(self.path), "--receipt", str(restored_receipt)],
        ]
        output = io.StringIO()
        with patch.dict(os.environ, {"CLOUDFLARE_DNS_API_TOKEN": "synthetic-private-token"}), \
                patch.object(DNS, "Cloudflare", return_value=self.client), redirect_stdout(output):
            for argv in arguments:
                # Function defaults are bound at definition time; use a local resolver fixture.
                reply = subprocess.CompletedProcess([], 0, stdout="8.8.4.4\n")
                with patch.object(sys, "argv", ["dns-reconcile.py", *argv]), \
                        patch.object(DNS.subprocess, "run", return_value=reply):
                    self.assertEqual(DNS.main(), 0)
        for path in (spec, planned, self.path, first_receipt, restored_receipt):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("synthetic-private-token", path.read_text())
        self.assertNotIn("synthetic-private-token", output.getvalue())
        self.assertFalse(DNS.load(restored_receipt)["resolver_verified"])

    def test_stale_receipt_is_rejected_before_provider_access(self):
        plan_path, receipt_path = self.root / "plan.json", self.root / "receipt.json"
        DNS.save(plan_path, self.plan())
        DNS.save(receipt_path, {"verified": True})
        with patch.object(sys, "argv", ["dns-reconcile.py", "apply", "--plan", str(plan_path),
                                      "--checkpoint", str(self.path), "--receipt", str(receipt_path)]), \
                patch.object(DNS, "Cloudflare") as factory, redirect_stderr(io.StringIO()):
            self.assertEqual(DNS.main(), 1)
        factory.assert_not_called()


class AdapterTests(unittest.TestCase):
    def test_provider_http_error_does_not_echo_body_or_token(self):
        from urllib.error import HTTPError
        client = DNS.Cloudflare("synthetic-private-token")
        failure = HTTPError("https://example.invalid", 403, "synthetic-private-token", {}, None)
        with patch.object(DNS, "urlopen", side_effect=failure):
            with self.assertRaises(DNS.OperationError) as caught:
                client.request("GET", "/zones/" + ZONE)
        self.assertNotIn("synthetic-private-token", str(caught.exception))
        self.assertIn("403", str(caught.exception))

    def test_provider_rejects_paginated_or_incomplete_records(self):
        client = DNS.Cloudflare("synthetic-token")
        for info in ({"total_pages": 2}, {"total_count": 3}):
            client.request = lambda *_: {"result": [], "result_info": info}
            with self.assertRaisesRegex(DNS.OperationError, "Incomplete"):
                client.records(ZONE, "gateway.example.invalid")

    def test_resolver_refuses_extra_addresses_and_cname_and_failed_command(self):
        responses = [(0, "8.8.4.4\n8.8.8.8\n"), (0, "alias.example.invalid\n8.8.4.4\n"),
                     (1, "8.8.4.4\n"), (0, "8.8.4.4\n")]
        for code, answer in responses:
            result = subprocess.CompletedProcess([], code, stdout=answer)
            with self.subTest(answer=answer), patch.object(DNS.subprocess, "run", return_value=result), \
                    patch.object(DNS.time, "monotonic", side_effect=[0, 0, 2, 2]), \
                    patch.object(DNS.time, "sleep"):
                self.assertEqual(DNS.wait_for_dns("gateway.example.invalid", "8.8.4.4", budget=1),
                                 code == 0 and answer == "8.8.4.4\n")


if __name__ == "__main__":
    unittest.main()
