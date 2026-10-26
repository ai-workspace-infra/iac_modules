import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('dev_dns',ROOT/'dev-onwalk-dns-create.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
ADDRESS='93.184.216.34';ACCOUNT='a'*32


def inputs():
    host={'name':m.HOST,'label':m.HOST,'instance_id':'123','ip':ADDRESS,'region':'jp-test',
          'groups':['dev','k3s'],'host_vars':{'cloud_provider':'akamai-cloud','k3s_platform_cluster_name':m.HOST}}
    raw=json.dumps({m.TARGET:{m.HOST:host}}).encode()
    plan={'schema':'dev-onwalk-dns/v1','environment':'dev','feature_id':'xconnect-referral','zone':m.ZONE,
          'hostnames':list(m.NAMES),'gitops_sha':'b'*40,'cmdb_sha256':hashlib.sha256(raw).hexdigest(),'operation_id':'run-123',
          'expected_target':{'target_id':m.TARGET,'name':m.HOST,'label':m.HOST,'instance_id':'123','region':'jp-test','account':'test-dev'}}
    return plan,raw


class FakeLinode:
    def __init__(self):self.calls=[];self.address=ADDRESS;self.label=m.HOST;self.duplicate=False
    def get(self,path,label=None):
        self.calls.append((path,label))
        if path=='/profile':return {'username':'test-dev'}
        row={'id':123,'label':self.label,'ipv4':[self.address],'status':'running','region':'jp-test'}
        if '?' in path:return {'pages':1,'results':2 if self.duplicate else 1,'data':[row,row] if self.duplicate else [row]}
        return row


class FakeCloudflare:
    def __init__(self):self.rows={};self.calls=[];self.fail_name=None;self.race_name=None;self.count={};self.lost_response=False
    def zone_id(self,zone):self.calls.append(('GET_ZONE',zone));return 'zone'
    def request(self,method,path):
        self.calls.append((method,path));assert method=='GET'
        return {'id':'zone','name':'onwalk.net','status':'active','account':{'id':ACCOUNT}}
    def records(self,zone,name):
        self.calls.append(('GET_RECORD',name));self.count[name]=self.count.get(name,0)+1
        if name==self.race_name and self.count[name]==2:self.rows[name]=[{'id':'foreign','name':name,'type':'AAAA','content':'::1'}]
        return copy.deepcopy(self.rows.get(name,[]))
    def create(self,zone,payload):
        self.calls.append(('POST',payload['name']))
        if payload['name']==self.fail_name and not self.lost_response:raise m.Error('fake create failure')
        row=dict(payload,id='id-'+str(len(self.rows)+1));self.rows[payload['name']]=[row]
        if payload['name']==self.fail_name:raise m.Error('lost response after create')
        return copy.deepcopy(row)
    def update(self,*args):raise AssertionError('no PUT allowed')
    def delete(self,*args):raise AssertionError('no DELETE allowed')


class DevDNS(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'checkpoint.json';self.plan,self.raw=inputs();self.cf=FakeCloudflare();self.linode=FakeLinode()
    def run_owner(self,apply=True):return m.execute(self.plan,self.raw,self.path,self.cf,self.linode,ACCOUNT,apply)
    def posts(self):return [x for x in self.cf.calls if x[0]=='POST']

    def test_full_six_preflight_create_and_same_record_id_retry(self):
        result=self.run_owner();self.assertEqual(result['result'],'CREATED_API_VERIFIED');self.assertEqual(len(self.posts()),6)
        before_post=self.cf.calls[:self.cf.calls.index(self.posts()[0])]
        self.assertEqual({x[1] for x in before_post if x[0]=='GET_RECORD'},set(m.NAMES))
        original=result['created_records'];again=self.run_owner();self.assertEqual(again['created_records'],original)
        self.assertEqual(len(self.posts()),6);self.assertEqual(self.path.stat().st_mode&0o777,0o600)

    def test_dry_run_is_read_only_and_does_not_claim_created(self):
        self.assertEqual(self.run_owner(False)['result'],'PLANNED');self.assertFalse(self.posts());self.assertFalse(self.path.exists())

    def test_any_preexisting_A_AAAA_or_CNAME_stops_all_writes(self):
        for kind in ('A','AAAA','CNAME'):
            self.cf=FakeCloudflare();name=m.NAMES[-1]
            self.cf.rows[name]=[{'id':'unowned','name':name,'type':kind,'content':ADDRESS}]
            self.assertRaises(m.Error,self.run_owner);self.assertFalse(self.posts());self.assertFalse(self.path.exists())

    def test_wrong_zone_names_environment_and_cmdb_hash_refused_before_provider(self):
        for key,value in [('zone','svc.plus'),('environment','uat'),('hostnames',list(m.NAMES[:-1])),('cmdb_sha256','f'*64)]:
            self.plan,_=inputs();self.plan[key]=value
            self.assertRaises(m.Error,self.run_owner);self.assertFalse(self.linode.calls);self.assertFalse(self.cf.calls)

    def test_wrong_current_IP_label_and_duplicate_resource_refused(self):
        for field,value in [('address','93.184.216.35'),('label','web-saas-k3s-v5'),('duplicate',True)]:
            self.linode=FakeLinode();setattr(self.linode,field,value)
            self.assertRaises(m.Error,self.run_owner);self.assertFalse(self.cf.calls)

    def test_partial_failure_retains_ids_and_can_resume_without_rewriting(self):
        self.cf.fail_name=m.NAMES[2]
        self.assertRaises(m.Error,self.run_owner)
        state=json.loads(self.path.read_text());self.assertEqual(state['result'],'BLOCKED_PARTIAL');self.assertEqual(len(state['records']),2)
        known=copy.deepcopy(state['records']);self.cf.fail_name=None
        result=self.run_owner();self.assertEqual(len(result['created_records']),6)
        self.assertTrue(all(result['created_records'][name]==rid for name,rid in known.items()))

    def test_owned_record_id_target_or_marker_change_is_not_adopted(self):
        self.run_owner();post_count=len(self.posts());name=m.NAMES[0];original=copy.deepcopy(self.cf.rows[name][0])
        for key,value in [('id','different-id'),('content','93.184.216.35'),('comment','other-owner')]:
            self.cf.rows[name][0]=dict(original,**{key:value})
            self.assertRaises(m.Error,self.run_owner);self.assertEqual(len(self.posts()),post_count)

    def test_concurrent_record_prevents_next_create_and_retains_prior_ids(self):
        self.cf.race_name=m.NAMES[2];self.assertRaises(m.Error,self.run_owner)
        self.assertEqual(len(self.posts()),2);self.assertEqual(len(json.loads(self.path.read_text())['records']),2)

    def test_lost_create_response_does_not_adopt_unknown_record_id(self):
        self.cf.fail_name=m.NAMES[0];self.cf.lost_response=True
        self.assertRaises(m.Error,self.run_owner);self.assertEqual(json.loads(self.path.read_text())['records'],{})
        self.cf.fail_name=None;before=len(self.posts())
        self.assertRaises(m.Error,self.run_owner);self.assertEqual(len(self.posts()),before)

    def test_address_change_during_batch_stops_without_deleting_created_record(self):
        original=self.cf.create
        def create(zone,payload):
            row=original(zone,payload);self.linode.address='93.184.216.35';return row
        self.cf.create=create
        self.assertRaises(m.Error,self.run_owner)
        self.assertEqual(len(self.posts()),1);self.assertEqual(len(json.loads(self.path.read_text())['records']),1)

    def test_zone_account_mismatch_prevents_all_creates(self):
        self.cf.request=lambda *args:{'id':'zone','name':m.ZONE,'status':'active','account':{'id':'f'*32}}
        self.assertRaises(m.Error,self.run_owner);self.assertFalse(self.posts())

    def test_changed_target_plan_cannot_reuse_checkpoint(self):
        self.run_owner();self.plan['gitops_sha']='c'*40
        self.assertRaises(m.Error,self.run_owner);self.assertEqual(len(self.posts()),6)

if __name__=='__main__':unittest.main()
