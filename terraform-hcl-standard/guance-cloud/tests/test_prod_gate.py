import copy
import unittest

import helpers  # noqa: F401
from prod_gate import UAT_GATES, evaluate
from state_contract import canonical_state_key

ISSUE = "https://github.com/ai-workspace-infra/iac_modules/issues/425"


def passing_record():
    return {
        "requested_by": "alice",
        "uat_acceptance": {g: {"status": "verified", "verified_at": "2026-11-01", "verified_by": "alice", "evidence": ISSUE} for g in UAT_GATES},
        "uat": {"workspace_alias": "xworktech-uat", "project": "xworktech.com", "management_credential_id": "key-uat", "state_key": canonical_state_key(environment="uat", project="xworktech.com", account="xworktech-uat")},
        "prod": {"workspace_alias": "xworktech-prod", "project": "xworktech.com", "management_credential_id": "key-prod", "state_key": canonical_state_key(environment="prod", project="xworktech.com", account="xworktech-prod")},
        "prod_plan_review": {"reviewed_by": "bob", "no_delete_or_replace": True, "plan_run": ISSUE},
        "authorization": {"approved_by": "bob", "approved_at": "2026-11-02", "issue_url": ISSUE, "scope": "prod-apply"},
    }


class ProdGateTest(unittest.TestCase):
    def test_complete_record_passes(self):
        self.assertEqual(evaluate(passing_record()), [])

    def test_empty_record_is_blocked(self):
        self.assertGreaterEqual(len(evaluate({})), len(UAT_GATES))

    def test_offline_only_evidence_never_passes(self):
        record = passing_record()
        record["uat_acceptance"]["monitors_and_mute"]["status"] = "offline-only"
        self.assertTrue(any("monitors_and_mute" in p for p in evaluate(record)))

    def test_each_uat_gate_is_required(self):
        for gate in UAT_GATES:
            record = passing_record()
            del record["uat_acceptance"][gate]
            self.assertTrue(any(gate in p for p in evaluate(record)), gate)

    def test_isolation_is_required(self):
        for field, value, fragment in (
            ("workspace_alias", "xworktech-uat", "own workspace"),
            ("management_credential_id", "key-uat", "own management credential"),
        ):
            record = passing_record()
            record["prod"][field] = value
            if field == "workspace_alias":
                record["prod"]["state_key"] = canonical_state_key(environment="prod", project="xworktech.com", account=value)
            self.assertTrue(any(fragment in p for p in evaluate(record)), field)
        record = passing_record()
        record["prod"]["state_key"] = record["uat"]["state_key"]
        self.assertTrue(evaluate(record))

    def test_authorization_must_be_explicit_and_independent(self):
        record = passing_record()
        record["authorization"]["approved_by"] = "alice"
        self.assertTrue(any("approver must differ" in p for p in evaluate(record)))
        record = passing_record()
        del record["authorization"]
        self.assertTrue(any("authorization" in p for p in evaluate(record)))
        record = passing_record()
        record["authorization"]["scope"] = "plan"
        self.assertTrue(evaluate(record))

    def test_plan_review_must_exclude_destructive_changes(self):
        record = copy.deepcopy(passing_record())
        record["prod_plan_review"]["no_delete_or_replace"] = False
        self.assertTrue(evaluate(record))



class ExampleRecordTest(unittest.TestCase):
    def test_shipped_example_is_always_blocked(self):
        import json

        record = json.loads((helpers.ROOT / "docs/prod-acceptance.example.json").read_text())
        problems = evaluate(record)
        self.assertGreaterEqual(len(problems), len(UAT_GATES))

    def test_prod_workdir_cannot_be_rendered(self):
        from guance_manifest import validate_manifest

        document = helpers.fixture()
        document["global"]["environment"] = "prod"
        with self.assertRaises(ValueError):
            validate_manifest(document)


if __name__ == "__main__":
    unittest.main()
