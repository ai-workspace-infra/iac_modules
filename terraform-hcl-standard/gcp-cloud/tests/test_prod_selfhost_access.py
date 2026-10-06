"""Fictional cloud command fixtures; never opens real cloud access."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class ProdAccessTests(unittest.TestCase):
    def fixture(self, directory):
        p = Path(directory)
        binary = p / 'bin'
        binary.mkdir()
        (binary / 'gcloud').write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
args=' '.join(sys.argv[1:])
p=Path(os.environ['FAKE_CLOUD_DIR'])
with (p/'calls').open('a') as f: f.write(args+'\\n')
if 'auth login' in args: pass
elif 'auth print-access-token' in args: print('fictional-runtime-token')
elif 'instances describe' in args: print((p/'facts.json').read_text())
elif 'firewall-rules describe' in args: print((p/'firewall.json').read_text())
elif 'firewall-rules list' in args:
 if (p/'rule').exists(): print(os.environ['FAKE_RULE'])
elif 'firewall-rules create' in args: (p/'rule').write_text('fixture')
elif 'firewall-rules delete' in args: (p/'rule').unlink(missing_ok=True)
elif 'os-login describe-profile' in args: print(json.dumps({'posixAccounts':[{'operatingSystemType':'LINUX','username':'sa_123'}]}))
elif 'os-login ssh-keys add' in args or 'os-login ssh-keys remove' in args: pass
else: raise SystemExit(1)
''')
        (binary / 'gcloud').chmod(0o700)
        (binary / 'curl').write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
url=sys.argv[-1]
expected='https://oslogin.googleapis.com/v1/users/github-actions-prod%40open-platform-prod.iam.gserviceaccount.com/loginProfile?projectId=open-platform-prod'
if url != expected: raise SystemExit(1)
p=Path(os.environ['FAKE_CLOUD_DIR'])
(p/'profile-url').write_text(url)
print(json.dumps({'posixAccounts':[{'operatingSystemType':'LINUX','username':os.environ.get('FAKE_PROFILE_USER','sa_123')}]}))
''')
        (binary / 'curl').chmod(0o700)
        disk = 'projects/open-platform-prod/zones/asia-east1-a/disks/web-saas-prod-data'
        cmdb = {'environment': 'prod', 'project_id': 'open-platform-prod',
                'deploy_account': 'github-actions-prod@open-platform-prod.iam.gserviceaccount.com',
                'web-saas-prod': {'provider': 'gcp-cloud', 'zone': 'asia-east1-a',
                    'provisioning_model': 'STANDARD', 'groups': ['web_saas'],
                    'ip': '1.1.1.1', 'ansible_user': 'sa_123',
                    'data_disk': {'id': disk, 'mount_path': '/data'}}}
        path = p / 'cmdb.json'
        path.write_text(json.dumps(cmdb))
        principal = cmdb['deploy_account']
        (p / 'wif.json').write_text(json.dumps({'type': 'external_account',
          'service_account_impersonation_url': 'https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/' + principal + ':generateAccessToken'}))
        facts = {'name': 'web-saas-prod', 'status': 'RUNNING', 'deletionProtection': True,
                 'scheduling': {'provisioningModel': 'STANDARD'},
                 'metadata': {'items': [{'key': 'enable-oslogin', 'value': 'TRUE'}]},
                 'tags': {'items': ['web-saas-ssh']},
                 'networkInterfaces': [{'network': 'https://www.googleapis.com/compute/v1/projects/open-platform-prod/global/networks/web-saas-prod-gcp', 'accessConfigs': [{'natIP': '1.1.1.1'}]}],
                 'disks': [{'deviceName': 'web-saas-prod-data', 'autoDelete': False,
                           'source': 'https://www.googleapis.com/compute/v1/' + disk}]}
        (p / 'facts.json').write_text(json.dumps(facts))
        firewall = {'name': 'web-saas-prod-gcp-spot-ssh', 'direction': 'INGRESS', 'disabled': False,
          'network': 'https://www.googleapis.com/compute/v1/projects/open-platform-prod/global/networks/web-saas-prod-gcp',
          'sourceRanges': ['10.73.0.0/25', '10.73.0.128/25'], 'targetTags': ['web-saas-ssh'],
          'allowed': [{'IPProtocol': 'tcp', 'ports': ['22']}]}
        (p / 'firewall.json').write_text(json.dumps(firewall))
        return dict(os.environ, PATH=str(binary) + ':' + os.environ['PATH'], FAKE_CLOUD_DIR=str(p),
          FAKE_RULE='web-saas-prod-ci-123-1', CMDB_FILE=str(path),
          EXPECTED_CMDB_SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
          GOOGLE_GHA_CREDS_PATH=str(p / 'wif.json'), RUNNER_TEMP=str(p),
          ACCESS_DIR=str(p / 'prod-native-access-123-1'), GITHUB_RUN_ID='123',
          GITHUB_RUN_ATTEMPT='1', SOURCE_IP='8.8.8.8', GITHUB_ACTIONS='true')

    def execute(self, phase, env):
        return subprocess.run(['bash', str(ROOT / 'scripts/pipeline/prod-selfhost-access.sh'), phase],
                              env=env, capture_output=True, text=True)

    def test_open_close_binds_live_target_and_revokes(self):
        with tempfile.TemporaryDirectory() as d:
            env = self.fixture(d)
            result = self.execute('open', env)
            self.assertEqual(result.returncode, 0, result.stderr)
            access = json.loads((Path(env['ACCESS_DIR']) / 'access.json').read_text())
            self.assertEqual(access['instance'], 'web-saas-prod')
            self.assertEqual(access['source_range'], '8.8.8.8/32')
            self.assertEqual(access['oslogin_key_ttl'], '45m')
            result = self.execute('close', env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(Path(env['ACCESS_DIR']).exists())
            self.assertFalse((Path(d) / 'rule').exists())
            calls = (Path(d) / 'calls').read_text()
            self.assertIn('ssh-keys remove', calls)
            self.assertNotIn('instances start', calls)
            self.assertNotIn('0.0.0.0/0', calls)
            self.assertNotIn('os-login describe-profile', calls)
            self.assertIn('projectId=open-platform-prod', (Path(d) / 'profile-url').read_text())

    def test_profile_mismatch_revokes_key_and_rule(self):
        with tempfile.TemporaryDirectory() as d:
            env = self.fixture(d)
            env['FAKE_PROFILE_USER'] = 'sa_456'
            self.assertNotEqual(self.execute('open', env).returncode, 0)
            self.assertFalse(Path(env['ACCESS_DIR']).exists())
            self.assertFalse((Path(d) / 'rule').exists())
            self.assertIn('ssh-keys remove', (Path(d) / 'calls').read_text())

    def test_public_or_additional_permanent_sources_refuse_before_access(self):
        for sources in [['0.0.0.0/0'], ['0.0.0.0/0', '10.73.0.0/25', '10.73.0.128/25']]:
            with tempfile.TemporaryDirectory() as d:
                env = self.fixture(d)
                path = Path(d) / 'firewall.json'
                facts = json.loads(path.read_text())
                facts['sourceRanges'] = sources
                path.write_text(json.dumps(facts))
                self.assertNotEqual(self.execute('open', env).returncode, 0)
                calls = (Path(d) / 'calls').read_text()
                self.assertNotIn('ssh-keys add', calls)
                self.assertNotIn('firewall-rules create', calls)

    def test_bad_artifact_or_directory_refuses_before_cloud_commands(self):
        for key, value in [('EXPECTED_CMDB_SHA256', '0' * 64), ('ACCESS_DIR', '/tmp/unowned')]:
            with tempfile.TemporaryDirectory() as d:
                env = self.fixture(d)
                env[key] = value
                self.assertNotEqual(self.execute('open', env).returncode, 0)
                self.assertFalse((Path(d) / 'calls').exists())

    def test_changed_live_disk_refuses_before_key_or_rule_creation(self):
        with tempfile.TemporaryDirectory() as d:
            env = self.fixture(d)
            p = Path(d) / 'facts.json'
            v = json.loads(p.read_text())
            v['disks'][0]['autoDelete'] = True
            p.write_text(json.dumps(v))
            self.assertNotEqual(self.execute('open', env).returncode, 0)
            calls = (Path(d) / 'calls').read_text()
            self.assertNotIn('ssh-keys add', calls)
            self.assertNotIn('firewall-rules create', calls)


if __name__ == '__main__':
    unittest.main()
