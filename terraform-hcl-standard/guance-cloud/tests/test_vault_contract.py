import re
import unittest
from pathlib import Path

import helpers
import yaml

VAULT = Path(helpers.ROOT, "vault/uat")
BASE = "kv/data/uat/platform/observability/guance/xworktech-uat"
STATE = "kv/data/CICD/uat/iac_state"


def policy_paths(name):
    text = (VAULT / "policies" / f"{name}.hcl").read_text()
    blocks = re.findall(r'path\s+"([^"]+)"\s*\{\s*capabilities\s*=\s*\[([^\]]*)\]\s*\}', text)
    assert len(blocks) == text.count("path "), "unparsed path block"
    return {path: [c.strip().strip('"') for c in caps.split(",")] for path, caps in blocks}


def readable(policy, path):
    return path in policy and "read" in policy[path]  # exact paths only: no globs in these policies


class VaultContractTest(unittest.TestCase):
    def test_policies_are_exact_read_only(self):
        for policy_file in (VAULT / "policies").glob("*.hcl"):
            for path, caps in policy_paths(policy_file.stem).items():
                self.assertNotRegex(path, r"[*+]", policy_file.name)
                self.assertEqual(caps, ["read"], f"{policy_file.name}:{path}")
                self.assertNotIn("/prod/", path)
                self.assertNotIn("/data/data/", path)

    def test_purpose_separation(self):
        terraform, query, ingest = (policy_paths(n) for n in ("guance-uat-terraform", "guance-uat-query", "guance-uat-ingest"))
        self.assertTrue(readable(terraform, f"{BASE}/management"))
        self.assertTrue(readable(terraform, STATE))
        self.assertFalse(readable(terraform, f"{BASE}/query"))
        self.assertFalse(readable(terraform, f"{BASE}/ingest"))
        self.assertEqual(set(query), {f"{BASE}/query"})
        self.assertEqual(set(ingest), {f"{BASE}/ingest"})
        for policy in (query, ingest):
            self.assertFalse(readable(policy, f"{BASE}/management"))
            self.assertFalse(readable(policy, STATE))

    def test_uat_cannot_read_prod_records(self):
        for policy_file in (VAULT / "policies").glob("*.hcl"):
            for path in policy_paths(policy_file.stem):
                self.assertFalse(path.startswith("kv/data/prod/") or "/prod/" in path or "xworktech-prod" in path)
                self.assertNotIn("CICD/prod", path)

    def test_terraform_policy_covers_each_declared_notify_object(self):
        document = helpers.fixture()
        paths = set(policy_paths("guance-uat-terraform"))
        for entry in document["notify_objects"]:
            self.assertIn(f"{BASE}/notify/{entry['id']}", paths)

    def test_roles_bind_workflow_ref_and_policies(self):
        for role_file in (VAULT / "roles").glob("*.yaml"):
            spec = yaml.safe_load(role_file.read_text())
            role = spec["role"]
            self.assertEqual(role["bound_audiences"], ["vault"])
            self.assertTrue(role["token_no_default_policy"])
            self.assertEqual(role["token_type"], "batch")
            self.assertLessEqual(int(role["token_max_ttl"].rstrip("m")), 30)
            for policy in role["token_policies"]:
                self.assertTrue((VAULT / "policies" / f"{policy}.hcl").exists())
            if spec.get("pending_owner"):
                continue
            claims = role["bound_claims"]
            self.assertTrue(claims["job_workflow_ref"].endswith("@refs/heads/main"))
            self.assertEqual(claims["ref"], "refs/heads/main")
            self.assertIn("environment", claims)

    def test_apply_role_requires_protected_environment(self):
        apply_role = yaml.safe_load((VAULT / "roles/guance-uat-apply.yaml").read_text())["role"]
        plan_role = yaml.safe_load((VAULT / "roles/guance-uat-plan.yaml").read_text())["role"]
        self.assertEqual(apply_role["bound_claims"]["environment"], "uat-guance-apply")
        self.assertNotEqual(plan_role["bound_claims"]["environment"], apply_role["bound_claims"]["environment"])

    def test_ingest_role_is_not_widened_to_terraform_workflow(self):
        spec = yaml.safe_load((VAULT / "roles/guance-uat-ingest.yaml").read_text())
        self.assertTrue(spec["pending_owner"])
        self.assertNotIn("guance-uat.yml", spec["role"]["bound_claims"]["job_workflow_ref"])


if __name__ == "__main__":
    unittest.main()
