import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cmdb_collect_gcp as collector
import cmdb_collect_scope as scope_runner
from cmdb_observations_v1 import (
    ContractError,
    reconcile_observations,
    resource_key,
    validate_envelope,
)


class CollectorTests(unittest.TestCase):
    def collect(self, fetch, *, project="project-a", scope="shared", kind="compute", region=None):
        with patch.object(collector, "access_token", return_value="test-only"):
            return collector.collect(project, scope, kind, region, "a" * 40, "metadata", fetch)

    def test_pagination_and_allowlist(self):
        item = {"id": "123", "name": "same-name", "zone": "zones/asia-east1-a", "status": "RUNNING", "metadata": {"startup-script": "sensitive"}}
        responses = iter([{"items": {"zones/a": {"instances": [item]}}, "nextPageToken": "two"}, {"items": {}}])
        document = self.collect(lambda *_: next(responses))
        self.assertEqual(document["run"]["outcome"], "success")
        self.assertNotIn("metadata", document["observations"][0])
        self.assertIn("123", document["observations"][0]["native_resource_id"])
        self.assertEqual(
            document["observations"][0]["resource_key"],
            "gcp:project-a:asia-east1:projects/project-a/zones/asia-east1-a/instances/123",
        )
        self.assertEqual(document["observations"][0]["runtime_form"], "vm")
        self.assertIn("last_observed_at", document["observations"][0])
        validate_envelope(document)

    def test_pagination_duplicate_replay_is_idempotent(self):
        item = {
            "id": "123",
            "name": "vm-123",
            "zone": "zones/asia-east1-a",
            "status": "RUNNING",
            "networkInterfaces": [{"networkIP": "10.0.0.5", "accessConfigs": [{"natIP": "198.51.100.5"}]}],
        }
        responses = iter(
            [
                {"items": {"zones/asia-east1-a": {"instances": [item]}}, "nextPageToken": "two"},
                {"items": {"zones/asia-east1-a": {"instances": [item]}}},
            ]
        )
        document = self.collect(lambda *_: next(responses))
        self.assertEqual(document["run"]["outcome"], "success")
        self.assertEqual(len(document["observations"]), 1)
        validated = validate_envelope(document)
        self.assertEqual(len(validated["observations"]), 1)

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
        observation = collector.run_observation(
            {
                "uid": "immutable-uid",
                "name": "projects/p/locations/r/services/s",
                "uri": "https://s-123.a.run.app",
                "terminalCondition": {"state": "CONDITION_SUCCEEDED"},
                "template": {"containers": [{"env": [{"value": "sensitive"}]}]},
            },
            "p",
            "r",
            "shared",
        )
        self.assertEqual(observation["resource_kind"], "serverless_service")
        self.assertEqual(observation["runtime_form"], "serverless")
        self.assertIsNone(observation["ssh_host"])
        self.assertIsNone(observation["primary_ip"])
        self.assertEqual(observation["resource_key"], "gcp:p:r:projects/p/locations/r/services/immutable-uid")
        self.assertNotIn("template", observation)
        self.assertEqual(observation["provider_state"], "ready")

    def test_k3s_node_classified_distinct_from_plain_vm(self):
        k3s_item = {
            "id": "9001",
            "name": "web-saas-k3s-v5",
            "zone": "zones/asia-northeast1-a",
            "status": "RUNNING",
            "tags": {"items": ["k3s_server", "prod"]},
            "networkInterfaces": [{"networkIP": "10.10.0.9", "accessConfigs": [{"natIP": "203.0.113.9"}]}],
        }
        obs = collector.compute_observation(k3s_item, "open-platform-prod", "prod")
        self.assertEqual(obs["runtime_form"], "k3s_node")
        self.assertEqual(obs["region"], "asia-northeast1")
        self.assertEqual(obs["primary_ip"], "203.0.113.9")
        self.assertEqual(obs["ssh_host"], "203.0.113.9")

    def test_envelope_rejects_cross_env_cross_region_and_serverless_fake_ip(self):
        base_run = {
            "run_id": "run-1",
            "collector": "gcp-cloudrun",
            "owner_sha": "a" * 40,
            "scope": "prod",
            "account_ref": "open-platform-prod",
            "project_ref": "open-platform-prod",
            "region_ref": "asia-east1",
            "started_at": "2026-10-25T10:00:00Z",
            "completed_at": "2026-10-25T10:00:05Z",
            "outcome": "success",
            "scope_complete": True,
        }
        valid_obs = {
            "provider": "gcp",
            "account_ref": "open-platform-prod",
            "project_ref": "open-platform-prod",
            "resource_kind": "serverless_service",
            "native_resource_id": "projects/open-platform-prod/locations/asia-east1/services/uid-1",
            "region": "asia-east1",
            "scope": "prod",
            "name": "prod-accounts",
            "provider_state": "ready",
            "provider_state_raw": "CONDITION_SUCCEEDED",
            "source": "provider_api",
            "observed_at": "2026-10-25T10:00:03Z",
            "attributes": {},
        }

        # Cross-environment mismatch (run=prod, obs=uat)
        with self.assertRaisesRegex(ContractError, "conflicts with run.scope"):
            validate_envelope(
                {
                    "schema_version": "cmdb.observations.v1",
                    "run": base_run,
                    "observations": [{**valid_obs, "scope": "uat"}],
                }
            )

        # Cross-region mismatch (run.region_ref=asia-east1, obs.region=us-central1)
        with self.assertRaisesRegex(ContractError, "conflicts with run.region_ref"):
            validate_envelope(
                {
                    "schema_version": "cmdb.observations.v1",
                    "run": base_run,
                    "observations": [{**valid_obs, "region": "us-central1"}],
                }
            )

        # Serverless observation with fabricated ssh_host or primary_ip must be rejected
        with self.assertRaisesRegex(ContractError, "serverless and cannot have ssh_host"):
            validate_envelope(
                {
                    "schema_version": "cmdb.observations.v1",
                    "run": base_run,
                    "observations": [{**valid_obs, "ssh_host": "198.51.100.1"}],
                }
            )

    def test_reconciliation_lifecycle_replay_deletion_and_partial_failure_protection(self):
        desired = [
            {
                "provider": "gcp",
                "project_ref": "open-platform-prod",
                "region": "asia-east1",
                "environment": "prod",
                "resource_kind": "compute",
                "runtime_form": "vm",
                "native_resource_id": "projects/open-platform-prod/zones/asia-east1-a/instances/vm-1",
                "name": "web-saas-prod",
            },
            {
                "provider": "gcp",
                "project_ref": "open-platform-prod",
                "region": "asia-east1",
                "environment": "prod",
                "resource_kind": "compute",
                "runtime_form": "vm",
                "native_resource_id": "projects/open-platform-prod/zones/asia-east1-b/instances/vm-2",
                "name": "worker-prod",
            },
            {
                "provider": "gcp",
                "project_ref": "open-platform-prod",
                "region": "asia-east1",
                "environment": "prod",
                "resource_kind": "serverless_service",
                "runtime_form": "serverless",
                "native_resource_id": "projects/open-platform-prod/locations/asia-east1/services/uid-accounts",
                "name": "prod-accounts",
            },
            {
                "provider": "cloudflare",
                "project_ref": "svc.plus",
                "region": "global",
                "environment": "prod",
                "resource_kind": "serverless_worker",
                "runtime_form": "serverless",
                "native_resource_id": "workers/frontend-router-prod",
                "name": "frontend-router-prod",
            },
        ]

        vm1_obs = {
            "provider": "gcp",
            "account_ref": "open-platform-prod",
            "project_ref": "open-platform-prod",
            "resource_kind": "compute",
            "native_resource_id": "projects/open-platform-prod/zones/asia-east1-a/instances/vm-1",
            "region": "asia-east1",
            "scope": "prod",
            "name": "web-saas-prod",
            "provider_state": "running",
            "provider_state_raw": "RUNNING",
            "public_endpoint": "198.51.100.10",
            "private_endpoint": "10.70.0.10",
            "source": "provider_api",
            "observed_at": "2026-10-25T10:00:02Z",
            "attributes": {"zone": "asia-east1-a"},
        }
        vm2_obs = {
            "provider": "gcp",
            "account_ref": "open-platform-prod",
            "project_ref": "open-platform-prod",
            "resource_kind": "compute",
            "native_resource_id": "projects/open-platform-prod/zones/asia-east1-b/instances/vm-2",
            "region": "asia-east1",
            "scope": "prod",
            "name": "worker-prod",
            "provider_state": "running",
            "provider_state_raw": "RUNNING",
            "public_endpoint": "198.51.100.11",
            "private_endpoint": "10.70.0.11",
            "source": "provider_api",
            "observed_at": "2026-10-25T10:00:02Z",
            "attributes": {"zone": "asia-east1-b"},
        }
        run_obs = {
            "provider": "gcp",
            "account_ref": "open-platform-prod",
            "project_ref": "open-platform-prod",
            "resource_kind": "serverless_service",
            "native_resource_id": "projects/open-platform-prod/locations/asia-east1/services/uid-accounts",
            "region": "asia-east1",
            "scope": "prod",
            "name": "prod-accounts",
            "provider_state": "ready",
            "provider_state_raw": "CONDITION_SUCCEEDED",
            "public_endpoint": "https://prod-accounts.a.run.app",
            "source": "provider_api",
            "observed_at": "2026-10-25T10:00:03Z",
            "attributes": {"service_name": "prod-accounts"},
        }

        env_compute_t1 = {
            "schema_version": "cmdb.observations.v1",
            "run": {
                "run_id": "run-c1",
                "collector": "gcp-compute",
                "owner_sha": "a" * 40,
                "scope": "prod",
                "account_ref": "open-platform-prod",
                "project_ref": "open-platform-prod",
                "region_ref": "all-zones",
                "resource_kind": "compute",
                "started_at": "2026-10-25T10:00:00Z",
                "completed_at": "2026-10-25T10:00:05Z",
                "outcome": "success",
                "scope_complete": True,
            },
            # Include vm1_obs twice to verify idempotent replay within an envelope
            "observations": [vm1_obs, vm1_obs, vm2_obs],
        }
        env_run_t1 = {
            "schema_version": "cmdb.observations.v1",
            "run": {
                "run_id": "run-s1",
                "collector": "gcp-cloudrun",
                "owner_sha": "a" * 40,
                "scope": "prod",
                "account_ref": "open-platform-prod",
                "project_ref": "open-platform-prod",
                "region_ref": "asia-east1",
                "resource_kind": "serverless_service",
                "started_at": "2026-10-25T10:00:00Z",
                "completed_at": "2026-10-25T10:00:06Z",
                "outcome": "success",
                "scope_complete": True,
            },
            "observations": [run_obs],
        }

        # Step 1: Initial reconciliation (plus replaying env_compute_t1 twice)
        report_t1 = reconcile_observations(
            [env_compute_t1, env_compute_t1, env_run_t1],
            desired_resources=desired,
        )
        self.assertEqual(report_t1["summary"]["declared_count"], 4)
        self.assertEqual(report_t1["summary"]["active_count"], 3)
        self.assertEqual(report_t1["summary"]["observed_active_count"], 3)
        self.assertEqual(report_t1["summary"]["unobserved_count"], 1)  # Cloudflare worker not yet collected
        self.assertEqual(report_t1["summary"]["deleted_count"], 0)
        self.assertEqual(
            report_t1["resources"]["cloudflare:svc.plus:global:workers/frontend-router-prod"]["status"],
            "unobserved",
        )

        # Step 2: Partial API failure on gcp-compute at T2 (only vm-1 returned before HTTP 503 on page 2).
        # vm-2 MUST NOT be marked deleted! It must be marked collection_failed and remain lifecycle='present'.
        env_compute_t2_partial = {
            "schema_version": "cmdb.observations.v1",
            "run": {
                "run_id": "run-c2-partial",
                "collector": "gcp-compute",
                "owner_sha": "a" * 40,
                "scope": "prod",
                "account_ref": "open-platform-prod",
                "project_ref": "open-platform-prod",
                "region_ref": "all-zones",
                "resource_kind": "compute",
                "started_at": "2026-10-25T10:05:00Z",
                "completed_at": "2026-10-25T10:05:05Z",
                "outcome": "partial",
                "scope_complete": False,
                "error_class": "http_503",
            },
            "observations": [{**vm1_obs, "observed_at": "2026-10-25T10:05:02Z"}],
        }
        report_t2 = reconcile_observations(
            [env_compute_t2_partial],
            desired_resources=desired,
            prior_resources=report_t1["resources"],
        )
        vm2_key = "gcp:open-platform-prod:asia-east1:projects/open-platform-prod/zones/asia-east1-b/instances/vm-2"
        self.assertEqual(report_t2["resources"][vm2_key]["status"], "collection_failed")
        self.assertEqual(report_t2["resources"][vm2_key]["lifecycle"], "present")
        self.assertEqual(report_t2["resources"][vm2_key]["last_observed_at"], "2026-10-25T10:00:02Z")
        self.assertEqual(report_t2["summary"]["deleted_count"], 0)
        self.assertEqual(report_t2["summary"]["active_count"], 3)

        # Step 3: Complete run at T3 where vm-2 was genuinely deleted (only vm-1 exists).
        # Now vm-2 transitions to status='deleted' (lifecycle='deletion_confirmed') and is excluded from active_count.
        env_compute_t3_complete = {
            "schema_version": "cmdb.observations.v1",
            "run": {
                "run_id": "run-c3-complete",
                "collector": "gcp-compute",
                "owner_sha": "a" * 40,
                "scope": "prod",
                "account_ref": "open-platform-prod",
                "project_ref": "open-platform-prod",
                "region_ref": "all-zones",
                "resource_kind": "compute",
                "started_at": "2026-10-25T10:10:00Z",
                "completed_at": "2026-10-25T10:10:05Z",
                "outcome": "success",
                "scope_complete": True,
            },
            "observations": [{**vm1_obs, "observed_at": "2026-10-25T10:10:02Z"}],
        }
        report_t3 = reconcile_observations(
            [env_compute_t3_complete],
            desired_resources=desired,
            prior_resources=report_t2["resources"],
        )
        self.assertEqual(report_t3["resources"][vm2_key]["status"], "deleted")
        self.assertEqual(report_t3["resources"][vm2_key]["lifecycle"], "deletion_confirmed")
        self.assertEqual(report_t3["resources"][vm2_key]["last_observed_at"], "2026-10-25T10:00:02Z")
        self.assertEqual(report_t3["summary"]["deleted_count"], 1)
        self.assertEqual(report_t3["summary"]["active_count"], 2)

    def test_scope_runner_writes_reconciliation_report(self):
        scope_yaml = {
            "apiVersion": "inventory.svc.plus/v1",
            "kind": "CMDBCollectionScope",
            "metadata": {"name": "test-scope"},
            "spec": {
                "collectors": [
                    {
                        "name": "prod-cloudrun-asia-east1",
                        "enabled": True,
                        "provider": "gcp",
                        "kind": "cloudrun",
                        "project": "open-platform-prod",
                        "scope": "prod",
                        "region": "asia-east1",
                    }
                ]
            },
        }

        def fake_collect(project, scope, kind, region, owner_sha, auth):
            return {
                "schema_version": "cmdb.observations.v1",
                "run": {
                    "run_id": "run-scope-1",
                    "collector": f"gcp-{kind}",
                    "owner_sha": owner_sha,
                    "scope": scope,
                    "account_ref": project,
                    "project_ref": project,
                    "region_ref": region,
                    "resource_kind": "serverless_service",
                    "started_at": "2026-10-25T10:00:00Z",
                    "completed_at": "2026-10-25T10:00:02Z",
                    "outcome": "success",
                    "scope_complete": True,
                },
                "observations": [
                    collector.run_observation(
                        {
                            "uid": "uid-1",
                            "name": f"projects/{project}/locations/{region}/services/prod-accounts",
                            "uri": "https://prod-accounts.a.run.app",
                            "terminalCondition": {"state": "CONDITION_SUCCEEDED"},
                        },
                        project,
                        region,
                        scope,
                    )
                ],
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            scope_path = tmp / "scope.yaml"
            scope_path.write_text(json.dumps(scope_yaml), encoding="utf-8")
            report_path = tmp / "reconciliation-report.json"
            jobs = scope_runner.load_jobs(scope_path)
            summaries, report = scope_runner.execute_scope_jobs(
                jobs,
                tmp / "out",
                "a" * 40,
                collector_fn=fake_collect,
                report_path=report_path,
            )
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0]["outcome"], "success")
            self.assertTrue(report_path.is_file())
            loaded_report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded_report["summary"]["active_count"], 1)
            self.assertEqual(loaded_report["by_runtime_form"]["serverless"]["active_count"], 1)


if __name__ == "__main__":
    unittest.main()
