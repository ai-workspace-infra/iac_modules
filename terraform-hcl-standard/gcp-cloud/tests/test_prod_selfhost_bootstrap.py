import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_prod_selfhost.py"
SPEC = importlib.util.spec_from_file_location("bootstrap", SCRIPT)
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def identity_plan():
    changes = []
    for role in bootstrap.ROLES:
        changes.append({"address": f'google_project_iam_member.deploy["{role}"]', "mode": "managed",
                        "type": "google_project_iam_member", "change": {"actions": ["create"], "before": None,
                        "after": {"project": bootstrap.PROJECT, "role": role, "member": bootstrap.MEMBER, "condition": []},
                        "after_unknown": {"id": True}}})
    changes.append({"address": bootstrap.TARGETS["identity"][-1], "mode": "managed", "type": "google_project_service",
                    "change": {"actions": ["create"], "before": None, "after_unknown": {"id": True},
                    "after": {"project": bootstrap.PROJECT, "service": "orgpolicy.googleapis.com", "disable_on_destroy": False}}})
    return {"resource_changes": changes}


def policy_plan():
    return {"resource_changes": [{"address": bootstrap.POLICY, "mode": "managed", "type": "google_org_policy_policy",
             "change": {"actions": ["create"], "before": None, "after": {
                 "name": f"projects/{bootstrap.PROJECT_NUMBER}/policies/compute.vmExternalIpAccess",
                 "parent": f"projects/{bootstrap.PROJECT}", "spec": [{"rules": [{"allow_all": None, "deny_all": None,
                 "condition": [], "values": [{"allowed_values": [bootstrap.INSTANCE], "denied_values": None}]}]}]},
                 "after_unknown": {"spec": [{"etag": True, "update_time": True}]}}}]}


class BootstrapTests(unittest.TestCase):
    def test_plan_apply_digest_mismatch_and_post_apply_convergence(self):
        resources = [{"mode": "managed", "type": kind, "name": name, "instances": [{"attributes": {"id": name}}]}
                     for kind, name in (("google_service_account", "github_actions"),
                                        ("google_iam_workload_identity_pool", "github"),
                                        ("google_iam_workload_identity_pool_provider", "github"))]
        state = {"lineage": "existing", "serial": 1, "resources": resources}
        oidc = {"spec": {"pool_id": "github-actions", "provider_id": "github", "audience": "fixture",
                         "service_account_id": "github-actions-prod", "subjects": ["fixture"],
                         "state": {"endpoint": "fixture", "bucket": "fixture", "region": "fixture"}}}
        args = SimpleNamespace(gitops_dir=Path("/unused"), gitops_ref="a" * 40, iac_ref="b" * 40,
                               stage="identity", action="plan", approved_plan_sha256=None)
        calls = []
        applied = False

        def tf_run(_self, *argv):
            nonlocal applied
            calls.append(argv)
            if argv[:2] == ("state", "pull"):
                return json.dumps(state)
            if argv[0] == "version":
                return json.dumps({"terraform_version": "1.16.0", "provider_selections": {"registry.terraform.io/hashicorp/google": "7.46.1"}})
            if argv[0] == "show":
                plan = identity_plan()
                if applied:
                    for item in plan["resource_changes"]:
                        item["change"]["actions"] = ["no-op"]
                return json.dumps(plan)
            if argv[0] == "apply":
                applied = True
            return ""

        env = {key: "fixture" for key in bootstrap.STATE_ENV}
        with patch.dict(os.environ, env), patch.object(bootstrap, "verify_checkout"), \
             patch.object(bootstrap, "declarations", return_value=(oidc, {})), \
             patch.object(bootstrap, "runtime_environment", return_value={}), \
             patch.object(bootstrap.Terraform, "run", new=tf_run):
            plan_receipt = bootstrap.execute(args)
            self.assertEqual(plan_receipt["result"], "review-required")
            self.assertFalse(any(call[0] == "apply" for call in calls))
            args.action = "apply"
            args.approved_plan_sha256 = "0" * 64
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.execute(args)
            self.assertFalse(any(call[0] == "apply" for call in calls))
            args.approved_plan_sha256 = plan_receipt["approved_plan_sha256"]
            receipt = bootstrap.execute(args)
            self.assertEqual(receipt["result"], "converged")
            self.assertFalse(receipt["database_cutover_approved"])
            self.assertEqual(sum(call[0] == "apply" for call in calls), 1)

    def test_only_declared_project_roles_and_api_are_accepted(self):
        receipt = bootstrap.inspect_plan(identity_plan(), "identity")
        self.assertEqual(len(receipt), 3)
        self.assertEqual({entry["contract"].get("role") for entry in receipt} - {None}, set(bootstrap.ROLES))

    def test_delete_replace_other_resource_and_missing_targets_fail(self):
        for actions in (["delete"], ["delete", "create"], ["create", "delete"], []):
            plan = identity_plan()
            plan["resource_changes"][0]["change"]["actions"] = actions
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.inspect_plan(plan, "identity")
        plan = identity_plan()
        plan["resource_changes"][0]["address"] = "google_service_account.github_actions"
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.inspect_plan(plan, "identity")
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.inspect_plan({"resource_changes": []}, "identity")

    def test_org_admin_other_project_other_member_and_unknown_grants_fail(self):
        for key, value in (("role", "roles/orgpolicy.policyAdmin"), ("member", "serviceAccount:other@example.com"),
                           ("project", "open-platform-uat")):
            plan = identity_plan()
            plan["resource_changes"][0]["change"]["after"][key] = value
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.inspect_plan(plan, "identity")
        plan = identity_plan()
        plan["resource_changes"][0]["change"]["after_unknown"]["member"] = True
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.inspect_plan(plan, "identity")

    def test_exact_policy_accepts_computed_etag_and_null_empty_values(self):
        self.assertEqual(bootstrap.inspect_plan(policy_plan(), "external-ip")[0]["contract"]["allowed_instances"], [bootstrap.INSTANCE])

    def test_policy_widening_wrong_constraint_inheritance_and_removed_allowance_fail(self):
        cases = []
        for key, value in (("allow_all", "TRUE"), ("deny_all", "TRUE"), ("condition", [{"expression": "true"}])):
            plan = policy_plan()
            plan["resource_changes"][0]["change"]["after"]["spec"][0]["rules"][0][key] = value
            cases.append(plan)
        plan = policy_plan()
        plan["resource_changes"][0]["change"]["after"]["spec"][0]["inherit_from_parent"] = True
        cases.append(plan)
        plan = policy_plan()
        plan["resource_changes"][0]["change"]["after"]["name"] = "projects/986070475391/policies/other"
        cases.append(plan)
        plan = policy_plan()
        before = copy.deepcopy(plan["resource_changes"][0]["change"]["after"])
        before["spec"][0]["rules"][0]["values"][0]["allowed_values"].append("projects/open-platform-prod/zones/asia-east1-a/instances/other")
        plan["resource_changes"][0]["change"]["before"] = before
        cases.append(plan)
        for plan in cases:
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.inspect_plan(plan, "external-ip")

    def test_state_requires_existing_lineage_and_protected_resources(self):
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.state_snapshot({}, "identity")
        resources = [{"mode": "managed", "type": kind, "name": name, "instances": [{"attributes": {"id": name}}]}
                     for kind, name in (("google_service_account", "github_actions"),
                                        ("google_iam_workload_identity_pool", "github"),
                                        ("google_iam_workload_identity_pool_provider", "github"))]
        state = {"lineage": "existing", "serial": 1, "resources": resources}
        self.assertEqual(len(bootstrap.state_snapshot(state, "identity")["protected"]), 3)
        state["resources"].pop()
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.state_snapshot(state, "identity")

    def test_tokens_only_in_provider_environment_and_unsafe_overrides_removed(self):
        env = {key: "fixture" for key in bootstrap.STATE_ENV}
        env.update(TF_STATE_ENDPOINT="https://state.example.com", TF_STATE_BUCKET="existing-state-bucket",
                   GCP_BOOTSTRAP_ACCESS_TOKEN="short-test-token", TF_VAR_access_token="wrong",
                   TF_VAR_create_project="true", TF_CLI_ARGS_plan="-destroy", TF_LOG="DEBUG",
                   TF_LOG_PATH="/tmp/leak", AWS_SESSION_TOKEN="wrong", TF_WORKSPACE="other")
        with patch.dict(os.environ, env, clear=True):
            runtime = bootstrap.runtime_environment()
        self.assertEqual(runtime["GOOGLE_OAUTH_ACCESS_TOKEN"], "short-test-token")
        self.assertFalse(any(key.startswith(("TF_VAR_", "TF_CLI_ARGS", "TF_LOG")) for key in runtime))
        self.assertNotIn("TF_WORKSPACE", runtime)
        self.assertNotIn("AWS_SESSION_TOKEN", runtime)
        self.assertNotIn("GCP_BOOTSTRAP_ACCESS_TOKEN", runtime)

    def test_policy_403_not_misclassified_as_absent(self):
        for status in (401, 403, 429, 500):
            error = urllib.error.HTTPError("https://example.com", status, "failure", {}, None)
            with patch.object(bootstrap.urllib.request, "urlopen", side_effect=error):
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap.existing_policy("test-token")
        error = urllib.error.HTTPError("https://example.com", 404, "absent", {}, None)
        with patch.object(bootstrap.urllib.request, "urlopen", side_effect=error):
            self.assertIsNone(bootstrap.existing_policy("test-token"))

    def test_provider_diagnostics_never_echoed(self):
        result = type("Result", (), {"returncode": 1, "stdout": "secret-value", "stderr": "secret-value"})()
        with patch.object(bootstrap.subprocess, "run", return_value=result):
            with self.assertRaises(bootstrap.BootstrapError) as raised:
                bootstrap.Terraform(Path("/private/temporary"), {}).run("plan")
        self.assertNotIn("secret-value", str(raised.exception))

    def test_source_must_be_clean_fixed_sha_and_expected_repository(self):
        with patch.object(bootstrap.subprocess, "check_output", side_effect=["a" * 40, "git@github.com:ai-workspace-infra/gitops.git", ""]):
            bootstrap.verify_checkout(Path("/unused"), "a" * 40, "ai-workspace-infra/gitops")
        for outputs in (["b" * 40, "git@github.com:ai-workspace-infra/gitops.git", ""],
                        ["a" * 40, "https://github.com/other/gitops.git", ""],
                        ["a" * 40, "git@github.com:ai-workspace-infra/gitops.git", " M manifest.yaml"]):
            with patch.object(bootstrap.subprocess, "check_output", side_effect=outputs):
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap.verify_checkout(Path("/unused"), "a" * 40, "ai-workspace-infra/gitops")

    def test_digest_binds_roles_state_serial_and_sources(self):
        receipt = {"state": {"serial": 4}, "targets": bootstrap.inspect_plan(identity_plan(), "identity"), "iac_ref": "a" * 40}
        original = bootstrap.digest(receipt)
        for key, value in (("state", {"serial": 5}), ("iac_ref", "b" * 40), ("targets", [])):
            self.assertNotEqual(original, bootstrap.digest({**receipt, key: value}))


if __name__ == "__main__":
    unittest.main()
