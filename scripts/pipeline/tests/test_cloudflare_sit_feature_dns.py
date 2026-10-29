import importlib.util
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
import contextlib
import io
import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("feature_dns", ROOT / "cloudflare-sit-feature-dns.py")
MODULE = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
sys.path.insert(0, str(ROOT.parent))
import verify_dev_sit_target as TARGET_CHECK


class FeatureDnsContract(unittest.TestCase):
    def test_tagged_dns_requires_current_matching_provider_target(self):
        cmdb={'dev-k3s-v5':{'name':'dev-k3s-v5','label':'dev-k3s-v5','instance_id':'123','ip':'8.8.8.8'}}
        facts={'id':123,'label':'dev-k3s-v5','region':'jp-tyo-3','status':'running','ipv4':['8.8.8.8']}
        with patch.object(TARGET_CHECK,'_linode_get_one',return_value=(200,facts)) as lookup:
            observation=MODULE.verify_current_target(cmdb,'8.8.8.8','fake-read-token')
            lookup.assert_called_once_with('linode/instances/123','fake-read-token')
            self.assertEqual((observation['node'],observation['instance_id'],observation['ip']),('dev-k3s-v5','123','8.8.8.8'))
            self.assertIn('observed_at',observation)
        with patch.object(TARGET_CHECK,'_linode_get_one',return_value=(403,{})), self.assertRaises(MODULE.base.OperationError):
            MODULE.verify_current_target(cmdb,'8.8.8.8','fake-read-token')
        with patch.object(TARGET_CHECK,'_linode_get_one',return_value=(200,dict(facts,ipv4=['8.8.4.4']))), self.assertRaises(MODULE.base.OperationError):
            MODULE.verify_current_target(cmdb,'8.8.8.8','fake-read-token')

    def test_provider_denial_stops_before_dns_client_creation(self):
        cmdb={'dev-k3s-v5':{'name':'dev-k3s-v5','label':'dev-k3s-v5','instance_id':'123','ip':'8.8.8.8',
                             'groups':['dev','k3s','k3s_server','akamai_cloud']}}
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'cmdb.json';path.write_text(json.dumps(cmdb))
            repo='ai-workspace-infra/Platform-Orchestrator';ref=repo+'/.github/workflows/feature-lane-deploy.yml@refs/heads/main'
            candidate_path=Path(temp)/'candidate.json'
            candidate_path.write_text(json.dumps({'schema_version':'dev-feature-candidate/v2','result':'verified','stage':'sit','candidate_sha256':'a'*64,
                'projection':{'tagged_lane':{'feature_id':'sit-test-1483','feature_tag':'smoke-sit-test-1483','candidate_sha256':'a'*64}},
                'source':{'repository':repo,'workflow_ref':ref,'workflow_sha':'b'*40,'run_id':'123','run_attempt':'1'}}))
            env={'DNS_ZONE':'onwalk.net','DNS_ENVIRONMENT':'sit','FEATURE_ID':'sit-test-1483','FEATURE_DNS_SERVICE':'console',
                 'CMDB_FILE':str(path),'DEV_INGRESS_NODE':'dev-k3s-v5','LINODE_TOKEN':'fake-read-token','FEATURE_CANDIDATE_SHA256':'a'*64,
                 'FEATURE_CANDIDATE_RECEIPT':str(candidate_path),'GITHUB_REPOSITORY':repo,'GITHUB_REF':'refs/heads/main',
                 'FEATURE_CANDIDATE_RECEIPT_SHA256':hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
                 'CMDB_SHA256':hashlib.sha256(path.read_bytes()).hexdigest(),
                 'GITHUB_WORKFLOW_REF':ref,'GITHUB_SHA':'b'*40,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}
            with patch.dict(os.environ,env,clear=True), patch.object(MODULE,'requested_domain',return_value=('smoke-sit-test-1483-sit.onwalk.net','smoke-sit-test-1483')), patch.object(TARGET_CHECK,'_linode_get_one',return_value=(403,{})), patch.object(MODULE,'FeatureCloudflare') as client, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(MODULE.main(),1)
            client.assert_not_called()
            with patch.dict(os.environ,dict(env,CMDB_SHA256='f'*64),clear=True), patch.object(MODULE,'requested_domain',return_value=('smoke-sit-test-1483-sit.onwalk.net','smoke-sit-test-1483')), patch.object(TARGET_CHECK,'_linode_get_one') as lookup, patch.object(MODULE,'FeatureCloudflare') as client, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(MODULE.main(),1)
                lookup.assert_not_called();client.assert_not_called()
            for invalid in ('', 'bad', 'A'*64):
                with self.subTest(invalid=invalid), patch.dict(os.environ,dict(env,FEATURE_CANDIDATE_SHA256=invalid),clear=True), patch.object(MODULE,'requested_domain',return_value=('smoke-sit-test-1483-sit.onwalk.net','smoke-sit-test-1483')), patch.object(TARGET_CHECK,'_linode_get_one') as lookup, patch.object(MODULE,'FeatureCloudflare') as client, contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(MODULE.main(),1)
                    lookup.assert_not_called();client.assert_not_called()
            output=io.StringIO()
            with patch.dict(os.environ,env,clear=True), patch.object(MODULE,'requested_domain',return_value=('smoke-sit-test-1483-sit.onwalk.net','smoke-sit-test-1483')), patch.object(MODULE,'verify_current_target',return_value={'instance_id':'123'}), patch.object(MODULE.base.Config,'from_env',return_value=object()), patch.object(MODULE,'FeatureCloudflare'), patch.object(MODULE.base,'execute',return_value={}), contextlib.redirect_stdout(output):
                env.update(CLOUDFLARE_DNS_API_TOKEN='fake',CLOUDFLARE_ACCOUNT_ID='fake')
                os.environ.update(env)
                self.assertEqual(MODULE.main(),0)
            self.assertEqual(json.loads(output.getvalue())['candidate_sha256'],'a'*64)
            legacy=dict(env);legacy.pop('FEATURE_CANDIDATE_SHA256');legacy.pop('LINODE_TOKEN');output=io.StringIO()
            with patch.dict(os.environ,legacy,clear=True), patch.object(MODULE,'requested_domain',return_value=('xconnect-referral-sit.onwalk.net',None)), patch.object(TARGET_CHECK,'_linode_get_one') as lookup, patch.object(MODULE.base.Config,'from_env',return_value=object()), patch.object(MODULE,'FeatureCloudflare'), patch.object(MODULE.base,'execute',return_value={}), contextlib.redirect_stdout(output):
                self.assertEqual(MODULE.main(),0)
            lookup.assert_not_called()
            self.assertNotIn('candidate_sha256',json.loads(output.getvalue()))

    def test_tagged_candidate_receipt_rejects_wrong_run_or_identity(self):
        repo='ai-workspace-infra/Platform-Orchestrator';ref=repo+'/.github/workflows/feature-lane-deploy.yml@refs/heads/main'
        env={'GITHUB_REPOSITORY':repo,'GITHUB_REF':'refs/heads/main','GITHUB_WORKFLOW_REF':ref,'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'11','GITHUB_RUN_ATTEMPT':'1'}
        receipt={'schema_version':'dev-feature-candidate/v2','result':'verified','stage':'sit','candidate_sha256':'b'*64,
                 'projection':{'tagged_lane':{'feature_id':'sit-test-1483','feature_tag':'smoke-sit-test-1483','candidate_sha256':'b'*64}},
                 'source':{'repository':repo,'workflow_ref':ref,'workflow_sha':'a'*40,'run_id':'11','run_attempt':'1'}}
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'receipt.json';path.write_text(json.dumps(receipt))
            env['FEATURE_CANDIDATE_RECEIPT_SHA256']=hashlib.sha256(path.read_bytes()).hexdigest()
            MODULE.verify_candidate_receipt(str(path),'sit-test-1483','smoke-sit-test-1483','b'*64,env)
            for changed in ({'GITHUB_RUN_ID':'12'},{'GITHUB_REF':'refs/heads/other'},{'GITHUB_SHA':'c'*40}):
                with self.subTest(changed=changed),self.assertRaises(MODULE.base.OperationError):
                    MODULE.verify_candidate_receipt(str(path),'sit-test-1483','smoke-sit-test-1483','b'*64,{**env,**changed})
            with self.assertRaises(MODULE.base.OperationError):
                MODULE.verify_candidate_receipt(str(path),'sit-test-1483','other-sit-test-1483','b'*64,env)
            with self.assertRaises(MODULE.base.OperationError):
                MODULE.verify_candidate_receipt(str(path),'sit-test-1483','smoke-sit-test-1483','b'*64,{**env,'FEATURE_CANDIDATE_RECEIPT_SHA256':'c'*64})

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
