#!/usr/bin/env python3
"""Exercise the Akamai cleanup guard with local Terraform-state fixtures only."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
GUARD = ROOT / "scripts/pipeline/assert-destroy-scope.sh"


class AkamaiDestroyScopeTest(unittest.TestCase):
    def setUp(self):
        if not shutil.which("jq"):
            self.skipTest("jq is required by the production destroy guard")
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        bindir = self.root / "bin"
        bindir.mkdir()
        terraform = bindir / "terraform"
        terraform.write_text("#!/bin/sh\nprintf '%s\\n' \"$FAKE_TERRAFORM_STATE\"\n", encoding="utf-8")
        terraform.chmod(0o755)
        self.hosts = self.root / "hosts_manifest.json"
        self.acceptance = self.root / "acceptance.json"
        self.write_acceptance(accepted=True)

    def tearDown(self):
        self.tempdir.cleanup()

    def write_acceptance(self, accepted):
        self.acceptance.write_text(json.dumps({
            "environment": "uat",
            "namespace": "open-platform",
            "migration_complete": accepted,
            "source_unchanged_through_acceptance": accepted,
            "target_health_checks_passed": accepted,
            "source_health_checks_passed": accepted,
            "state_isolation_verified": accepted,
            "backup_reference": "backup://run/123" if accepted else "",
            "acceptance_reference": "https://github.com/example/acceptance/123" if accepted else "",
        }), encoding="utf-8")

    @staticmethod
    def state_with_label(label):
        return {"values": {"root_module": {"resources": [{
            "address": "linode_instance.host",
            "mode": "managed",
            "type": "linode_instance",
            "name": "host",
            "values": {"label": label},
        }]}}}

    def run_guard(self, namespace, state_label, expected_label=None):
        self.hosts.write_text(json.dumps({"hosts": [{"label": expected_label or state_label}]}), encoding="utf-8")
        state_key = f"terraform/uat/svc.plus/akamai-cloud/manbuzhe2026/{namespace}/terraform.tfstate"
        env = os.environ.copy()
        env.update({
            "PATH": f"{self.root / 'bin'}:{env['PATH']}",
            "FAKE_TERRAFORM_STATE": json.dumps(self.state_with_label(state_label)),
            "ENV_STEPS_ROUTE_OUTPUTS_CLOUD_PROVIDER": "akamai-cloud",
            "ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE": f"uat-platform-ops-toolkit-akamai-cloud-manbuzhe2026-{namespace}",
            "ENV_STEPS_ROUTE_OUTPUTS_STATE_KEY": state_key,
            "HOSTS_MANIFEST": str(self.hosts),
            "OPEN_PLATFORM_ACCEPTANCE_FILE": str(self.acceptance),
        })
        return subprocess.run(["bash", str(GUARD)], cwd=self.root, env=env, capture_output=True, text=True)

    def test_shared_selfhost_state_is_always_rejected(self):
        result = self.run_guard("selfhost", "ap-uat-ak-jp-jpn-tky")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("aggregate Akamai destroy namespace", result.stderr)

    def test_accepted_open_platform_cleanup_is_allowed(self):
        result = self.run_guard("open-platform", "open-platform-uat-ak-open-platform")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("verified in-profile instance", result.stdout)

    def test_source_instance_is_never_in_destroy_scope(self):
        result = self.run_guard("agent-proxy-jp", "observability.svc.plus")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("protected migration source", result.stderr)

    def test_temporary_namespace_cleanup_does_not_require_open_platform_attestation(self):
        self.write_acceptance(accepted=False)
        result = self.run_guard("agent-proxy-jp", "ap-uat-ak-jp-jpn-tky")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_open_platform_cleanup_requires_migration_health_and_state_isolation_attestation(self):
        self.write_acceptance(accepted=False)
        result = self.run_guard("open-platform", "open-platform-uat-ak-open-platform")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("migration, dual-end health", result.stderr)

    def test_accepted_single_namespace_cleanup_excludes_permanent_node(self):
        result = self.run_guard("agent-proxy-jp", "ap-uat-ak-jp-jpn-tky")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("verified in-profile instance", result.stdout)

    def test_state_must_match_only_the_selected_namespace_manifest(self):
        result = self.run_guard("agent-proxy-jp", "open-platform-uat-ak-open-platform", "ap-uat-ak-jp-jpn-tky")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("permanent open-platform resource", result.stderr)


if __name__ == "__main__":
    unittest.main()
