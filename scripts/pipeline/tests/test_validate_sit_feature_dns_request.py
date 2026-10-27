import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

PATH = Path(__file__).parents[1] / "validate-sit-feature-dns-request.py"
SPEC = importlib.util.spec_from_file_location("validate_sit_dns", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RequestTests(unittest.TestCase):
    def test_hash_bound_request_and_cmdb_validate(self):
        request = {"schema_version": "sit-feature-dns-request/v1", "result": "verified", "environment": "sit",
                   "feature_id": "feature-search", "namespace": "feature-search-sit",
                   "domains": MODULE.domains("feature-search"), "gitops_sha": "a" * 40,
                   "candidate_sha256": "b" * 64, "cmdb_artifact": "cmdb-1", "cmdb_sha256": "",
                   "instance_id": "12345", "request_artifact": "request-1",
                   "source": {"workflow_ref": "ai-workspace-infra/platform-ops-toolkit/.github/workflows/dev-feature-deploy.yml@refs/heads/main",
                              "run_id": "987", "run_attempt": "1"}}
        cmdb = {"dev-k3s-v5": {"ip": "172.237.5.48", "groups": ["dev", "k3s", "k3s_server", "akamai_cloud"]}}
        with tempfile.TemporaryDirectory() as tmp:
            req, node = Path(tmp) / "request.json", Path(tmp) / "cmdb.json"
            node.write_text(json.dumps(cmdb)); request["cmdb_sha256"] = hashlib.sha256(node.read_bytes()).hexdigest()
            req.write_text(json.dumps(request))
            env = {"REQUEST_PATH": str(req), "CMDB_PATH": str(node), "REQUEST_SHA256": hashlib.sha256(req.read_bytes()).hexdigest(),
                   "CMDB_SHA256": request["cmdb_sha256"], "REQUEST_ARTIFACT": "request-1", "CMDB_ARTIFACT": "cmdb-1",
                   "INSTANCE_ID": "12345", "GITOPS_SHA": "a" * 40, "CANDIDATE_SHA256": "b" * 64,
                   "GITHUB_RUN_ID": "987", "GITHUB_RUN_ATTEMPT": "1"}
            old = os.environ.copy()
            try:
                os.environ.update(env)
                self.assertEqual(MODULE.verify()["feature_id"], "feature-search")
            finally:
                os.environ.clear(); os.environ.update(old)

    def test_feature_id_domain_formula_is_strict(self):
        with self.assertRaises(ValueError):
            MODULE.domains("feature-../prod")


if __name__ == "__main__":
    unittest.main()
