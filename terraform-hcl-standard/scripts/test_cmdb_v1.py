import json
import tempfile
import unittest
from pathlib import Path

from cmdb_v1 import make_document, write_document


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


if __name__ == "__main__":
    unittest.main()
