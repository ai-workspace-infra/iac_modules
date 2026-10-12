import re
import unittest
from pathlib import Path

import helpers
import yaml
from test_vault_contract import BASE, STATE, policy_paths

WORKFLOW = Path(helpers.ROOT).parents[1] / ".github/workflows/guance-uat.yml"


def load():
    return yaml.safe_load(WORKFLOW.read_text())


def vault_paths(job):
    step = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("hashicorp/vault-action"))
    lines = [line.strip().rstrip(";").strip() for line in step["with"]["secrets"].splitlines() if line.strip()]
    return step, [line.split()[0] for line in lines]


class WorkflowContractTest(unittest.TestCase):
    def test_no_static_secrets_and_no_privileged_triggers(self):
        text = WORKFLOW.read_text()
        self.assertNotIn("secrets.", text)
        self.assertNotIn("pull_request_target", text)
        self.assertNotIn("&inputs", text)  # Actions YAML anchors are not relied upon

    def test_only_vault_jobs_may_mint_oidc_tokens(self):
        jobs = load()["jobs"]
        for name in ("offline", "grafana-fallback"):
            self.assertNotIn("id-token", jobs[name].get("permissions", {}))
            self.assertFalse(any("vault-action" in str(s.get("uses", "")) for s in jobs[name]["steps"]))
        for name in ("plan", "apply"):
            self.assertEqual(jobs[name]["permissions"], {"contents": "read", "id-token": "write"})

    def test_apply_is_gated_by_protected_environment_and_dedicated_role(self):
        jobs = load()["jobs"]
        self.assertEqual(jobs["apply"]["environment"], "uat-guance-apply")
        self.assertEqual(jobs["plan"]["environment"], "uat")
        self.assertEqual(vault_paths(jobs["apply"])[0]["with"]["role"], "github-actions-iac-modules-uat-guance-apply")
        self.assertEqual(vault_paths(jobs["plan"])[0]["with"]["role"], "github-actions-iac-modules-uat-guance-plan")
        self.assertEqual(jobs["apply"]["needs"], "plan")

    def test_vault_reads_match_the_policy_exactly(self):
        jobs = load()["jobs"]
        allowed = set(policy_paths("guance-uat-terraform"))
        for name in ("plan", "apply"):
            step, paths = vault_paths(jobs[name])
            self.assertFalse(step["with"]["exportEnv"])
            self.assertFalse(step["with"]["exportToken"])
            self.assertEqual({p for p in paths if p.startswith("kv/data/uat/")} | {p for p in paths if p.startswith("kv/data/CICD")}, set(paths))
            self.assertTrue(set(paths) <= allowed, set(paths) - allowed)
            self.assertIn(f"{BASE}/management", paths)
            self.assertIn(STATE, paths)
            self.assertNotIn(f"{BASE}/query", paths)
            self.assertNotIn(f"{BASE}/ingest", paths)

    def test_every_declared_notify_object_is_injected(self):
        document = helpers.fixture()
        text = WORKFLOW.read_text()
        for entry in document["notify_objects"]:
            self.assertIn(f"{BASE}/notify/{entry['id']} opt_set", text)
            self.assertIn(f"TF_VAR_guance_notify_{entry['id']}_opt_set", text)

    def test_grafana_fallback_is_independent_of_guance_jobs(self):
        job = load()["jobs"]["grafana-fallback"]
        self.assertNotIn("needs", job)
        self.assertTrue(re.search(r"fallback-only", job["if"]))
        text = "\n".join(str(step) for step in job["steps"]).lower()
        self.assertNotIn("guance", text.replace("guance-cloud/scripts", "").replace("grafana-fallback-check", ""))

    def test_second_plan_after_apply_must_be_empty(self):
        steps = load()["jobs"]["apply"]["steps"]
        self.assertTrue(any("--expect-no-changes" in str(s.get("run", "")) for s in steps))

    def test_only_cmdb_is_uploaded(self):
        for job in load()["jobs"].values():
            for step in job["steps"]:
                if str(step.get("uses", "")).startswith("actions/upload-artifact"):
                    self.assertTrue(step["with"]["path"].endswith("cmdb.json"))


if __name__ == "__main__":
    unittest.main()
