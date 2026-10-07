import copy
import json
from pathlib import Path
import unittest
from database_contract import validate, preflight, receipt, lookup_exists, Rejected
from vault_fake import FakeVault

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.spec=json.loads((Path(__file__).parent/'example.json').read_text())
        self.obs={'lookup_status':200,'existing_roles':['example_runtime'],'credential_available':{'runtime':True}}
    def test_valid_both_backends(self):
        validate(self.spec)
        self.spec['backend']='supabase_cloud'; validate(self.spec)
    def test_reject_matrix(self):
        fixtures=[('password','placeholder'),('dsn','postgresql://placeholder'),('arbitrary','value')]
        for key,value in fixtures:
            with self.subTest(key=key):
                spec=copy.deepcopy(self.spec); spec[key]=value
                with self.assertRaises(Rejected): validate(spec)
        mutations=[('identity','env','../prod'),('tls','mode','disable'),('safety','allow_rotation',True),('safety','allow_rebuild',True),('safety','allow_delete',True),('safety','allow_cutover',True),('safety','explicit_adoption',False),('repository_shas','playbooks','HEAD')]
        for obj,key,value in mutations:
            with self.subTest(obj=obj,key=key):
                spec=copy.deepcopy(self.spec); spec[obj][key]=value
                with self.assertRaises(Rejected): validate(spec)
    def test_nested_secret_and_owner(self):
        for i in (0,6):
            spec=copy.deepcopy(self.spec); spec['roles'][i]['dsn_secret_ref']='postgresql://placeholder'
            with self.assertRaises(Rejected): validate(spec)
    def test_distinct_purposes_and_names(self):
        for field in ('name','purpose'):
            spec=copy.deepcopy(self.spec); spec['roles'][1][field]=spec['roles'][0][field]
            with self.assertRaises(Rejected): validate(spec)
    def test_scoped_ref_cas(self):
        for key,value in [('path','prod/databases'),('expected_version',-1),('expected_version',True),('field','password')]:
            spec=copy.deepcopy(self.spec); spec['roles'][0]['dsn_secret_ref'][key]=value
            with self.assertRaises(Rejected): validate(spec)
    def test_403_never_missing(self):
        for status in (401,403,429,500,0):
            with self.assertRaises(Rejected): lookup_exists(status)
        self.assertFalse(lookup_exists(404)); self.assertTrue(lookup_exists(200))
    def test_existing_role_credentials_required(self):
        preflight(self.spec,self.obs)
        self.obs['credential_available']={}
        with self.assertRaisesRegex(Rejected,'existing_role_missing_credential'): preflight(self.spec,self.obs)
    def test_modes(self):
        self.spec['mode']='existing_external'; self.spec['safety']['explicit_adoption']=False
        with self.assertRaises(Rejected): validate(self.spec)
        self.spec['operation']='inspect'; preflight(self.spec,self.obs)
        self.obs['lookup_status']=404
        with self.assertRaises(Rejected): preflight(self.spec,self.obs)
    def test_strict_state(self):
        self.spec['backend']='supabase_cloud'
        with self.assertRaisesRegex(Rejected,'provider_secret_state_unsupported'): preflight(self.spec,self.obs)
    def test_receipt_allowlist(self):
        out=receipt(self.spec,'offline_pass',{'contract':'pass','permissions':'not_run'})
        serialized=json.dumps(out)
        for text in ('dsn','password','token','credential','postgresql://'): self.assertNotIn(text,serialized)
        with self.assertRaises(Rejected): receipt(self.spec,'offline_pass',{'provider_error':'secret'})
    def test_fake_vault_recovery_and_cas(self):
        vault=FakeVault(); path='fixture/databases/i/db/runtime'; value={'dsn':'PLACEHOLDER_ONLY'}
        vault.stage('op',path,value,0)
        with self.assertRaisesRegex(Rejected,'verification_failed'): vault.promote('op',lambda _:False)
        self.assertEqual(vault.active,{})
        vault.stage('op',path,value,0)
        self.assertEqual(vault.promote('op',lambda _:True),1)
        self.assertEqual(vault.promote('op',lambda _:True),1)
        with self.assertRaises(Rejected): vault.stage('op2',path,value,0)
        with self.assertRaises(Rejected): vault.stage('op',path,{'dsn':'OTHER_PLACEHOLDER'},0)
        with self.assertRaises(Rejected): vault.stage('legacy','prod/databases',value,0)

if __name__=='__main__': unittest.main()
