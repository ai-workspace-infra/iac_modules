import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cmdb_v1 import (
    build_resource_key,
    classify_runtime_form,
    infer_environment,
    infer_region,
    make_document,
    merge_documents,
    write_document,
)


class CmdbV1Test(unittest.TestCase):
    def test_document_has_canonical_hosts_and_legacy_host_key(self):
        hosts = {"web-saas-prod": {"ip": "198.51.100.10", "groups": ["web_saas"]}}
        document = make_document(
            hosts,
            cloud_provider="gcp-cloud",
            resource_paths="resources/svc.plus/prod/gcp/web-saas.yaml",
            project_id="open-platform-prod",
        )

        self.assertEqual(document["schema_version"], "cmdb.v1")
        self.assertEqual(document["environment"], "prod")
        self.assertEqual(document["hosts"], hosts)
        self.assertEqual(document["web-saas-prod"], hosts["web-saas-prod"])
        self.assertIn("observed_at", document)
        self.assertIn("last_observed_at", document)
        self.assertIn("resource_index", document)

    def test_writer_does_not_embed_absolute_resource_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cmdb.json"
            document = make_document(
                {"host": {"ip": "198.51.100.11"}},
                cloud_provider="aws",
                resource_paths="/runner/work/infra/gitops/resources/svc.plus/prod/aws/web-saas.yaml",
            )
            write_document(path, document)
            rendered = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            rendered["source_resources"],
            ["resources/svc.plus/prod/aws/web-saas.yaml"],
        )

    def test_secret_like_host_vars_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "runtime credentials"):
            make_document(
                {"host": {"ip": "198.51.100.12", "host_vars": {"API_TOKEN": "x"}}},
                cloud_provider="vultr",
                resource_paths="resources/svc.plus/uat/vultr/web-saas.yaml",
            )

    def test_vm_k3s_and_serverless_separation_and_resource_key(self):
        hosts = {
            "web-saas-prod": {
                "ip": "198.51.100.10",
                "zone": "asia-east1-a",
                "resource_id": "projects/open-platform-prod/zones/asia-east1-a/instances/1001",
                "groups": ["web_saas"],
            },
            "web-saas-k3s-v5": {
                "ip": "198.51.100.20",
                "region": "jp-tyo-3",
                "instance_id": "linode-9988",
                "provider": "akamai-cloud",
                "project_id": "svc.plus",
                "groups": ["web_saas", "k3s_server"],
                "host_vars": {
                    "deployment_mode": "kubernetes",
                    "k8s_cluster_name": "web-saas-k3s-v5",
                    "k8s_namespace": "web-saas-k3s-v5",
                },
            },
            "prod-accounts-run": {
                "resource_kind": "serverless_service",
                "runtime_form": "serverless",
                "region": "asia-east1",
                "resource_id": "projects/open-platform-prod/locations/asia-east1/services/uid-acct",
                "public_endpoint": "https://prod-accounts.a.run.app",
                "ssh_host": None,
                "primary_ip": None,
            },
        }
        serverless = {
            "frontend-router-prod": {
                "provider": "cloudflare",
                "project_id": "svc.plus",
                "region": "global",
                "resource_kind": "serverless_worker",
                "resource_id": "workers/frontend-router-prod",
                "public_endpoint": "https://console-serverless-prod.svc.plus",
            }
        }
        doc = make_document(
            hosts,
            cloud_provider="gcp-cloud",
            resource_paths="resources/svc.plus/prod/gcp/web-saas.yaml",
            project_id="open-platform-prod",
            observed_at="2026-10-25T10:00:00Z",
            serverless_resources=serverless,
        )

        # Serverless entries must NOT pollute SSH hosts
        self.assertIn("web-saas-prod", doc["hosts"])
        self.assertIn("web-saas-k3s-v5", doc["hosts"])
        self.assertNotIn("prod-accounts-run", doc["hosts"])
        self.assertNotIn("frontend-router-prod", doc["hosts"])
        self.assertIn("prod-accounts-run", doc["serverless_resources"])
        self.assertIn("frontend-router-prod", doc["serverless_resources"])

        idx = doc["resource_index"]
        vm_key = "gcp:open-platform-prod:asia-east1:projects/open-platform-prod/zones/asia-east1-a/instances/1001"
        k3s_key = "akamai:svc.plus:jp-tyo-3:linode-9988"
        run_key = "gcp:open-platform-prod:asia-east1:projects/open-platform-prod/locations/asia-east1/services/uid-acct"
        cf_key = "cloudflare:svc.plus:global:workers/frontend-router-prod"

        self.assertEqual(idx[vm_key]["runtime_form"], "vm")
        self.assertEqual(idx[vm_key]["primary_ip"], "198.51.100.10")
        self.assertEqual(idx[vm_key]["ssh_host"], "198.51.100.10")

        self.assertEqual(idx[k3s_key]["runtime_form"], "k3s_node")
        self.assertEqual(idx[k3s_key]["cluster"], "web-saas-k3s-v5")
        self.assertEqual(idx[k3s_key]["namespace"], "web-saas-k3s-v5")
        self.assertEqual(idx[k3s_key]["node"], "web-saas-k3s-v5")

        self.assertEqual(idx[run_key]["runtime_form"], "serverless")
        self.assertIsNone(idx[run_key]["ssh_host"])
        self.assertIsNone(idx[run_key]["primary_ip"])

        self.assertEqual(idx[cf_key]["runtime_form"], "serverless")
        self.assertIsNone(idx[cf_key]["ssh_host"])
        self.assertIsNone(idx[cf_key]["primary_ip"])

    def test_serverless_rejects_fabricated_ip_or_ssh_host(self):
        with self.assertRaisesRegex(ValueError, "serverless resource .* cannot define"):
            make_document(
                {
                    "bad-serverless": {
                        "runtime_form": "serverless",
                        "resource_kind": "serverless_service",
                        "region": "asia-east1",
                        "ip": "198.51.100.99",
                    }
                },
                cloud_provider="gcp-cloud",
                resource_paths="resources/svc.plus/prod/gcp/web-saas.yaml",
                project_id="open-platform-prod",
            )

        with self.assertRaisesRegex(ValueError, "fabricated|loopback|unspecified"):
            make_document(
                {"bad-vm": {"ip": "0.0.0.0", "region": "asia-east1"}},
                cloud_provider="gcp-cloud",
                resource_paths="resources/svc.plus/prod/gcp/web-saas.yaml",
                project_id="open-platform-prod",
            )

    def test_cross_environment_and_region_conflict_rejected(self):
        with self.assertRaisesRegex(ValueError, "span multiple environments"):
            infer_environment(["resources/svc.plus/prod/gcp/a.yaml", "resources/svc.plus/uat/gcp/b.yaml"])

        with self.assertRaisesRegex(ValueError, "conflicts with resource path environment"):
            infer_environment("resources/svc.plus/uat/gcp/web-saas.yaml", explicit="prod")

        with patch.dict(os.environ, {"DEPLOY_ENVIRONMENT": "prod"}, clear=False):
            with self.assertRaisesRegex(ValueError, "DEPLOY_ENVIRONMENT .* conflicts"):
                infer_environment("resources/svc.plus/uat/gcp/web-saas.yaml")

        # Zone us-central1-a overrides default cloud_region asia-east1 when not explicitly conflicting
        self.assertEqual(
            infer_region({"zone": "us-central1-a", "cloud_region": "asia-east1"}, default_region="asia-east1"),
            "us-central1",
        )
        # Explicit region conflicting with zone raises ValueError
        with self.assertRaisesRegex(ValueError, "conflicts with zone"):
            infer_region({"zone": "us-central1-a", "region": "asia-east1"})

    def test_idempotent_deduplication_on_replay_and_merge(self):
        hosts = {
            "alias-a": {
                "ip": "198.51.100.10",
                "zone": "asia-east1-a",
                "resource_id": "https://www.googleapis.com/compute/v1/projects/open-platform-prod/zones/asia-east1-a/instances/1001",
                "observed_at": "2026-10-25T10:00:00Z",
            },
            "alias-b": {
                "ip": "198.51.100.10",
                "zone": "asia-east1-a",
                "resource_id": "projects/open-platform-prod/zones/asia-east1-a/instances/1001",
                "observed_at": "2026-10-25T10:05:00Z",
            },
        }
        doc = make_document(
            hosts,
            cloud_provider="gcp-cloud",
            resource_paths="resources/svc.plus/prod/gcp/web-saas.yaml",
            project_id="open-platform-prod",
        )
        self.assertEqual(len(doc["resource_index"]), 1)
        self.assertEqual(len(doc["hosts"]), 1)
        self.assertIn("alias-b", doc["hosts"])

        replayed = merge_documents(doc, doc)
        self.assertEqual(len(replayed["resource_index"]), 1)
        self.assertEqual(len(replayed["hosts"]), 1)

        uat_doc = make_document(
            {"uat-host": {"ip": "198.51.100.55", "region": "asia-east1"}},
            cloud_provider="gcp-cloud",
            resource_paths="resources/svc.plus/uat/gcp/web-saas.yaml",
            project_id="open-platform-uat",
        )
        with self.assertRaisesRegex(ValueError, "cannot merge CMDB documents across environments"):
            merge_documents(doc, uat_doc)


if __name__ == "__main__":
    unittest.main()
