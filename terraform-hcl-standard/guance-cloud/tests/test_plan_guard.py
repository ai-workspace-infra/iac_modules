import unittest

import helpers  # noqa: F401
from plan_guard import evaluate, summarize


def plan(*changes):
    return {"resource_changes": [{"address": a, "change": {"actions": acts, **({"importing": {"id": "x"}} if imp else {})}} for a, acts, imp in changes]}


class PlanGuardTest(unittest.TestCase):
    def problems(self, *changes, **kwargs):
        return evaluate(summarize(plan(*changes)), **kwargs)

    def test_create_only_passes(self):
        self.assertEqual(self.problems(("guance_dashboard.a", ["create"], False)), [])

    def test_delete_and_replace_fail(self):
        self.assertTrue(self.problems(("guance_dashboard.a", ["delete"], False)))
        self.assertIn("replace", self.problems(("guance_dashboard.a", ["delete", "create"], False))[0])

    def test_explicit_delete_allowance(self):
        self.assertEqual(self.problems(("guance_mute.a", ["delete"], False), allow_delete={"guance_mute.a"}), [])

    def test_import_with_diff_needs_review(self):
        self.assertTrue(self.problems(("guance_dashboard.a", ["update"], True)))
        self.assertEqual(self.problems(("guance_dashboard.a", ["no-op"], True)), [])
        self.assertEqual(self.problems(("guance_dashboard.a", ["update"], True), allow_import_updates=True), [])

    def test_second_plan_must_be_empty(self):
        self.assertTrue(self.problems(("guance_dashboard.a", ["update"], False), expect_no_changes=True))
        self.assertEqual(self.problems(("guance_dashboard.a", ["no-op"], False), expect_no_changes=True), [])

    def test_summary_carries_no_values(self):
        raw = plan(("guance_notify_object.a", ["create"], False))
        raw["resource_changes"][0]["change"]["after"] = {"opt_set": "SECRET"}
        self.assertNotIn("SECRET", str(summarize(raw)))


if __name__ == "__main__":
    unittest.main()
