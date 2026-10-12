import argparse
import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("gitops_cloud_targets", ROOT / "scripts/pipeline/gitops_cloud_targets.py")
targets = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(targets)


class GitOpsCloudTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "target.yaml"
        self.output = self.root / "output"

    def write(self, value):
        self.manifest.write_text(yaml.safe_dump(value), encoding="utf-8")

    def test_gcp_read_and_exact_contract_validation(self):
        self.write({"global": {"environment": "uat", "project_id": "open-platform-uat", "region": "asia-northeast1", "artifact_registry_location": "asia-northeast1"}})
        args = argparse.Namespace(manifest=self.manifest, mode="read", environment="", project_id="", region="", github_output=self.output)
        targets.gcp(args)
        self.assertEqual(self.output.read_text().splitlines(), ["project_id=open-platform-uat", "region=asia-northeast1"])
        args.mode, args.environment, args.project_id, args.region = "validate", "uat", "open-platform-uat", "asia-northeast1"
        targets.gcp(args)
        args.project_id = "other-project"
        with self.assertRaisesRegex(ValueError, "does not match GitOps"):
            targets.gcp(args)

    def test_gcp_rejects_registry_region_drift(self):
        self.write({"global": {"environment": "uat", "project_id": "open-platform-uat", "region": "asia-northeast1", "artifact_registry_location": "us-central1"}})
        args = argparse.Namespace(manifest=self.manifest, mode="validate", environment="uat", project_id="open-platform-uat", region="asia-northeast1", github_output=None)
        with self.assertRaisesRegex(ValueError, "Artifact Registry"):
            targets.gcp(args)

    def test_aws_oidc_requires_account_role_and_environment_subjects(self):
        repository = "ai-workspace-infra/platform-ops-toolkit"
        value = {
            "apiVersion": "gitops.svc.plus/v1alpha1",
            "kind": "GitHubActionsOIDCConfig",
            "metadata": {"environment": "prod", "provider": "aws"},
            "spec": {
                "provider_url": "https://token.actions.githubusercontent.com",
                "audience": "sts.amazonaws.com",
                "aws": {"account_id": "123456789012", "region": "us-east-1", "role_name": "deploy", "role_arn": "arn:aws:iam::123456789012:role/deploy"},
                "subjects": [
                    f"repo:{repository}:ref:refs/heads/main",
                    f"repo:{repository}:ref:refs/tags/v*",
                    f"repo:{repository}:environment:production",
                ],
            },
        }
        self.write(value)
        args = argparse.Namespace(manifest=self.manifest, environment="prod", account="123456789012", github_output=self.output)
        targets.aws(args)
        self.assertIn("role_arn=arn:aws:iam::123456789012:role/deploy", self.output.read_text())
        value["spec"]["subjects"].pop()
        self.write(value)
        with self.assertRaisesRegex(ValueError, "trust contract"):
            targets.aws(args)


if __name__ == "__main__":
    unittest.main()
