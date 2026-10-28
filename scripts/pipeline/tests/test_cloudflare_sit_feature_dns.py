import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("feature_dns", ROOT / "cloudflare-sit-feature-dns.py")
MODULE = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FeatureDnsContract(unittest.TestCase):
    def test_tagged_dns_requires_current_matching_provider_target(self):
        cmdb={'dev-k3s-v5':{'name':'dev-k3s-v5','label':'dev-k3s-v5','instance_id':'123','ip':'8.8.8.8'}}
        facts={'id':123,'label':'dev-k3s-v5','region':'jp-tyo-3','status':'running','ipv4':['8.8.8.8']}
        with patch.object(MODULE.target_check,'_linode_get_one',return_value=(200,facts)) as lookup:
            MODULE.verify_current_target(cmdb,'8.8.8.8','fake-read-token')
            lookup.assert_called_once_with('linode/instances/123','fake-read-token')
        with patch.object(MODULE.target_check,'_linode_get_one',return_value=(403,{})), self.assertRaises(MODULE.base.OperationError):
            MODULE.verify_current_target(cmdb,'8.8.8.8','fake-read-token')
        with patch.object(MODULE.target_check,'_linode_get_one',return_value=(200,dict(facts,ipv4=['8.8.4.4']))), self.assertRaises(ValueError):
            MODULE.verify_current_target(cmdb,'8.8.8.8','fake-read-token')

    def test_tagged_owner_requires_exact_candidate_hostname_and_ownership(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        contract_path = Path(directory.name) / 'contract.yaml'
        declaration = {'format': 'sit-feature-domain-contract/v2', 'environment': 'sit', 'zone': 'onwalk.net',
                       'namespace': 'feature-{feature_id}-sit',
                       'services': {'console': '{feature_tag}-sit.onwalk.net',
                                    'accounts': 'accounts-{feature_tag}-sit.onwalk.net',
                                    'billing': 'billing-{feature_tag}-sit.onwalk.net'},
                       'dns': {'provider_owner': 'iac_modules', 'record_type': 'A',
                               'target': 'fresh-cmdb-dev-k3s-v5-ip', 'ttl_seconds': 60, 'proxied': False,
                               'conflict_policy': 'refuse-unowned-record',
                               'cleanup_policy': 'exact-feature-id-and-tag-owned-records-only'}}
        contract_path.write_text(yaml.safe_dump(declaration))
        env = {'RESOURCE_OPERATION': 'sit-feature-tag-dns', 'FEATURE_TAG': 'smoke-sit-test-1483',
               'FEATURE_HOSTNAME': 'smoke-sit-test-1483-sit.onwalk.net', 'FEATURE_DOMAIN_CONTRACT': str(contract_path)}
        result = MODULE.requested_domain(env, 'sit-test-1483', 'console', 'onwalk.net')
        self.assertEqual(result, (env['FEATURE_HOSTNAME'], env['FEATURE_TAG']))
        for changes in ({'FEATURE_TAG': 'smoke-sit-test-1484'},
                        {'FEATURE_HOSTNAME': 'other-sit.onwalk.net'},
                        {'FEATURE_HOSTNAME': ''}, {'RESOURCE_OPERATION': 'sit-feature-dns'}):
            with self.subTest(changes=changes), self.assertRaises(MODULE.base.OperationError):
                MODULE.requested_domain(dict(env, **changes), 'sit-test-1483', 'console', 'onwalk.net')
        client = MODULE.FeatureCloudflare('test-token', 'a' * 32, 'sit-test-1483', env['FEATURE_TAG'])
        self.assertIn('feature-tag:smoke-sit-test-1483', client.create_payload({})['tags'])
        client.request = lambda *_: [{'name': env['FEATURE_HOSTNAME'], 'id': 'r',
                                     'tags': ['feature-id:sit-test-1483', 'owner:iac-modules']}]
        with self.assertRaises(MODULE.base.OperationError):
            client.records('zone', env['FEATURE_HOSTNAME'])
        declaration['zone'] = 'svc.plus'
        contract_path.write_text(yaml.safe_dump(declaration))
        with self.assertRaises(MODULE.base.OperationError):
            MODULE.requested_domain(env, 'sit-test-1483', 'console', 'onwalk.net')
        declaration['zone'] = 'onwalk.net'
        declaration['dns']['proxied'] = 0
        contract_path.write_text(yaml.safe_dump(declaration))
        with self.assertRaises(MODULE.base.OperationError):
            MODULE.requested_domain(env, 'sit-test-1483', 'console', 'onwalk.net')

    def test_sit_configuration_and_owned_creation_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {'DNS_ENVIRONMENT': 'sit', 'CLOUDFLARE_ACCOUNT_ID': 'a' * 32,
                   'DNS_ZONE': 'onwalk.net', 'DNS_RECORD_NAME': 'xconnect-referral-sit.onwalk.net',
                   'DNS_TARGET_IP': '172.237.5.48', 'DNS_CHECKPOINT_PATH': str(Path(directory) / 'dns.json'),
                   'DNS_WAIT_FOR_RESOLVER': 'false'}
            with self.assertRaises(MODULE.base.OperationError):
                MODULE.base.Config.from_env(env)
            config = MODULE.base.Config.from_env(env, allowed_environments=('sit',))
            client = MODULE.FeatureCloudflare('test-token', 'a' * 32, 'feature-xconnect-referral')
            records = []
            def request(method, path, payload=None):
                if method == 'GET' and path.startswith('/zones?'):
                    return [{'id': 'zone'}]
                if method == 'GET':
                    return list(records)
                if method == 'POST':
                    record = dict(payload, id='created')
                    records.append(record)
                    return record
                raise AssertionError('unexpected provider mutation')
            client.request = request
            self.assertEqual(MODULE.base.execute(config, client)['action'], 'create')
            checkpoint = json.loads(config.checkpoint.read_text())
            self.assertEqual(checkpoint['desired']['tags'], ['feature-id:feature-xconnect-referral', 'owner:iac-modules'])
            self.assertEqual(MODULE.base.execute(config, client)['action'], 'noop')
            self.assertEqual(len(records), 1)

    def test_tagged_domain_is_bound_to_feature_id_and_zone(self):
        self.assertEqual(MODULE.tagged_lane_domain('sit-test-1483', 'smoke-sit-test-1483', 'console', 'onwalk.net'), 'smoke-sit-test-1483-sit.onwalk.net')
        self.assertEqual(MODULE.tagged_lane_domain('sit-test-1483', 'smoke-sit-test-1483', 'accounts', 'onwalk.net'), 'accounts-smoke-sit-test-1483-sit.onwalk.net')
        for tag, zone in [('smoke-sit-test-1484', 'onwalk.net'), ('smoke-sit-test-1483', 'example.net')]:
            with self.subTest(tag=tag, zone=zone), self.assertRaises(MODULE.base.OperationError):
                MODULE.tagged_lane_domain('sit-test-1483', tag, 'console', zone)
        with self.assertRaises(MODULE.base.OperationError):
            MODULE.tagged_lane_domain('sit-test-1483', 'a' * 40 + '-sit-test-1483', 'accounts', 'onwalk.net')
        with self.assertRaises(MODULE.base.OperationError):
            MODULE.tagged_lane_domain('sit-test-', 'smoke-sit-test-', 'console', 'onwalk.net')

    def test_stable_feature_id_maps_to_service_names(self):
        self.assertEqual(MODULE.lane_domain("feature-xconnect-referral", "console", "onwalk.net"), "xconnect-referral-sit.onwalk.net")
        self.assertEqual(MODULE.lane_domain("feature-xconnect-referral", "accounts", "onwalk.net"), "accounts-xconnect-referral-sit.onwalk.net")
        self.assertEqual(MODULE.lane_domain("feature-xconnect-referral", "billing", "onwalk.net"), "billing-xconnect-referral-sit.onwalk.net")

    def test_cmdb_target_requires_exact_dev_k3s_identity_and_public_ip(self):
        cmdb = {"dev-k3s-v5": {"ip": "172.237.5.48", "groups": ["dev", "k3s", "k3s_server", "akamai_cloud"]}}
        self.assertEqual(MODULE.dev_ingress_ip(cmdb, "dev-k3s-v5"), "172.237.5.48")
        for bad_cmdb, node in ((cmdb, "other-node"), ({"dev-k3s-v5": {"ip": "127.0.0.1", "groups": ["dev", "k3s", "k3s_server", "akamai_cloud"]}}, "dev-k3s-v5"), ({"dev-k3s-v5": {"ip": "172.237.5.48", "groups": ["all_in_one"]}}, "dev-k3s-v5")):
            with self.subTest(node=node, cmdb=bad_cmdb), self.assertRaises(MODULE.base.OperationError):
                MODULE.dev_ingress_ip(bad_cmdb, node)

    def test_invalid_feature_service_and_zone_are_rejected(self):
        for feature_id, service, zone in (("../prod", "console", "onwalk.net"), ("Feature-A", "console", "onwalk.net"), ("xconnect-referral", "console", "onwalk.net"), ("feature-a-", "console", "onwalk.net"), ("feature-a", "postgresql", "onwalk.net"), ("feature-a", "console", "bad_zone"), ("feature-a", "console", "example.net")):
            with self.subTest(feature_id=feature_id, service=service, zone=zone), self.assertRaises(MODULE.base.OperationError):
                MODULE.lane_domain(feature_id, service, zone)


if __name__ == "__main__":
    unittest.main()
