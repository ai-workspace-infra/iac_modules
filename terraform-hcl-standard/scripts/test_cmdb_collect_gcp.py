import unittest
from unittest.mock import patch

import cmdb_collect_gcp as collector
from cmdb_observations_v1 import validate_envelope


class CollectorTests(unittest.TestCase):
    def collect(self, fetch):
        with patch.object(collector, "access_token", return_value="test-only"):
            return collector.collect("project-a", "shared", "compute", None, "a" * 40, "metadata", fetch)

    def test_pagination_and_allowlist(self):
        item = {"id": "123", "name": "same-name", "zone": "zones/asia-east1-a", "status": "RUNNING", "metadata": {"startup-script": "sensitive"}}
        responses = iter([{"items": {"zones/a": {"instances": [item]}}, "nextPageToken": "two"}, {"items": {}}])
        document = self.collect(lambda *_: next(responses))
        self.assertEqual(document["run"]["outcome"], "success")
        self.assertNotIn("metadata", document["observations"][0])
        self.assertIn("123", document["observations"][0]["native_resource_id"])
        validate_envelope(document)

    def test_partial_page_failure_is_not_empty_success(self):
        def fetch(url, headers):
            if "pageToken=" in url:
                raise collector.APIError("http_403")
            return {"items": {}, "nextPageToken": "two"}
        document = self.collect(fetch)
        self.assertEqual(document["run"]["outcome"], "failed")
        self.assertFalse(document["run"]["scope_complete"])

    def test_incomplete_aggregate(self):
        document = self.collect(lambda *_: {"unreachables": ["zones/a"]})
        self.assertFalse(document["run"]["scope_complete"])

    def test_loop_rejected(self):
        document = self.collect(lambda *_: {"nextPageToken": "repeat"})
        self.assertEqual(document["run"]["error_class"], "pagination_loop")

    def test_cloudrun_excludes_revision_and_environment_values(self):
        observation = collector.run_observation({"uid": "immutable-uid", "name": "projects/p/locations/r/services/s", "terminalCondition": {"state": "CONDITION_SUCCEEDED"}, "template": {"containers": [{"env": [{"value": "sensitive"}]}]}}, "p", "r", "shared")
        self.assertEqual(observation["resource_kind"], "serverless_service")
        self.assertNotIn("template", observation)
        self.assertEqual(observation["provider_state"], "ready")


if __name__ == "__main__":
    unittest.main()
