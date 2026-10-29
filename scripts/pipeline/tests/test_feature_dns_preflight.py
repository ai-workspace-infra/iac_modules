import datetime
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('dns_preflight', ROOT/'feature-dns-preflight.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class PreflightTest(unittest.TestCase):
 def test_requires_exact_fresh_target_and_candidate(self):
  with tempfile.TemporaryDirectory() as tmp:
   cmdb=Path(tmp)/'cmdb.json'; cmdb.write_text(json.dumps({'dev-k3s-v5':{'instance_id':'123'}}))
   observation=Path(tmp)/'target.json'
   row={'schema':'dev-sit-provider-observation/v1','result':'MATCH','node':'dev-k3s-v5','ip':'8.8.8.8','instance_id':'123',
        'cmdb_sha256':hashlib.sha256(cmdb.read_bytes()).hexdigest(),'candidate_sha256':'a'*64,
        'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
   observation.write_text(json.dumps(row))
   env={'FEATURE_CANDIDATE_RECEIPT':'receipt','FEATURE_ID':'sit-test-1483','FEATURE_TAG':'smoke-sit-test-1483',
        'FEATURE_CANDIDATE_SHA256':'b'*64,'FEATURE_DOMAIN_CONTRACT':'contract','FEATURE_DNS_SERVICE':'console',
        'FEATURE_HOSTNAME':'smoke-sit-test-1483-sit.onwalk.net','CMDB_FILE':str(cmdb),'CMDB_SHA256':row['cmdb_sha256'],
        'TARGET_OBSERVATION':str(observation),'FEATURE_CANDIDATE_RECEIPT_SHA256':'a'*64}
   with patch.object(p.owner,'verify_candidate_receipt'),patch.object(p.owner,'verify_domain_contract'),patch.object(p.owner,'dev_ingress_ip',return_value='8.8.8.8'):
    p.validate(env)
    for changes in ({'candidate_sha256':'c'*64},{'ip':'1.1.1.1'},{'observed_at':(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=21)).isoformat()}):
     observation.write_text(json.dumps({**row,**changes}))
     with self.subTest(changes=changes),self.assertRaises(ValueError):p.validate(env)

if __name__ == "__main__": unittest.main()
