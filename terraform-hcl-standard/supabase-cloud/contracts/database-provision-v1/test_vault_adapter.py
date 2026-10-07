from pathlib import Path
import json,unittest
from database_contract import Rejected
from vault_adapter import VaultAdapter,MockVaultTransport

class VaultTests(unittest.TestCase):
    def setUp(self):
        spec=json.loads((Path(__file__).parent/'example.json').read_text());self.identity=spec['identity'];self.ref=spec['roles'][1]['dsn_secret_ref']
        self.mock=MockVaultTransport();self.adapter=VaultAdapter(self.mock,'oidc/fixture');self.value={'dsn':'PLACEHOLDER_ONLY'}
    def stage(self):return self.adapter.stage(self.identity,'runtime',self.ref,'operation_1',self.value)
    def test_cas_verified_idempotent(self):
        handle=self.stage();self.assertEqual(self.stage(),handle)
        with self.assertRaisesRegex(Rejected,'staging_verification_failed'):self.adapter.promote(handle,lambda _:False)
        self.assertNotIn(self.ref['path'],self.mock.store)
        out=self.adapter.promote(handle,lambda _:True);self.assertEqual(out['version'],1)
        self.assertEqual(self.adapter.promote(handle,lambda _:True),out)
        self.assertNotIn('PLACEHOLDER_ONLY',json.dumps(out))
    def test_403_never_missing(self):
        self.mock.inject('GET','/v1/kv/data/'+self.ref['path']+'/_staging/operation_1',403)
        with self.assertRaisesRegex(Rejected,'vault_forbidden'):self.stage()
        self.assertEqual(self.mock.store,{})
    def test_stage_timeout_after_write_recovery(self):
        path='/v1/kv/data/'+self.ref['path']+'/_staging/operation_1';self.mock.inject('POST',path,'timeout_after')
        self.assertEqual(self.stage().staging_version,1)
    def test_stage_timeout_before_write_is_unknown(self):
        path='/v1/kv/data/'+self.ref['path']+'/_staging/operation_1';self.mock.inject('POST',path,'timeout_before')
        with self.assertRaisesRegex(Rejected,'staging_write_outcome_unknown'):self.stage()
        self.assertEqual(self.mock.store,{})
        self.assertEqual(self.stage().staging_version,1)
    def test_partial_active_failure_and_resume(self):
        handle=self.stage();path='/v1/kv/data/'+self.ref['path'];self.mock.inject('POST',path,'timeout_before')
        with self.assertRaisesRegex(Rejected,'active_write_outcome_unknown'):self.adapter.promote(handle,lambda _:True)
        self.assertIn(handle.staging_path,self.mock.store);self.assertNotIn(handle.active_path,self.mock.store)
        self.mock.inject('POST',path,'timeout_after')
        self.assertEqual(self.adapter.promote(handle,lambda _:True)['version'],1)
    def test_concurrent_cas_no_overwrite(self):
        handle=self.stage();self.mock.store[handle.active_path]={'version':1,'value':{'operation_id':'other','dsn':'OTHER_PLACEHOLDER'}}
        with self.assertRaisesRegex(Rejected,'active_cas_conflict'):self.adapter.promote(handle,lambda _:True)
        self.assertEqual(self.mock.store[handle.active_path]['value']['operation_id'],'other')
    def test_same_id_different_payload_rejected(self):
        self.stage()
        with self.assertRaisesRegex(Rejected,'staging_operation_conflict'):self.adapter.stage(self.identity,'runtime',self.ref,'operation_1',{'dsn':'OTHER_PLACEHOLDER'})
    def test_metadata_legacy_only_no_field_values(self):
        for path in ('prod/databases','prod/database-upgrade'):
            self.mock.store[path]={'version':5,'value':{'PROD_SUPABASE_READONLY_DSN':'PLACEHOLDER_ONLY'}}
            out=self.adapter.metadata({'apiVersion':'LegacySecretRef/v1','mount':'kv','path':path,'field':'PROD_SUPABASE_READONLY_DSN'})
            self.assertEqual(out['current_version'],5);self.assertNotIn('PLACEHOLDER_ONLY',json.dumps(out))
        self.assertTrue(all('/metadata/' in path for _,path,_ in self.mock.calls))
    def test_metadata_403_and_unknown_reject(self):
        ref={'apiVersion':'LegacySecretRef/v1','mount':'kv','path':'prod/databases','field':'PROD_SUPABASE_READONLY_DSN'}
        self.mock.inject('GET','/v1/kv/metadata/prod/databases',403)
        with self.assertRaisesRegex(Rejected,'vault_forbidden'):self.adapter.metadata(ref)
        ref['path']='prod/unapproved'
        with self.assertRaises(Rejected):self.adapter.metadata(ref)
    def test_real_access_and_old_writer_blocked(self):
        self.mock.fixture_only=False
        with self.assertRaisesRegex(Rejected,'real_vault_access_disabled'):VaultAdapter(self.mock,'oidc/fixture')
        self.identity['env']='prod'
        with self.assertRaises(Rejected):self.stage()
    def test_forged_handle_rejected_before_read(self):
        from vault_adapter import Staged
        handle=Staged('operation_1','fixture/databases/isolated/example/runtime','prod/databases',1,0)
        with self.assertRaises(Rejected):self.adapter.promote(handle,lambda _:True)
        self.assertEqual(self.mock.calls,[])
    def test_invalid_auth_ref_rejected(self):
        with self.assertRaises(Rejected):VaultAdapter(self.mock,'oidc/../../../ token')
    def test_transport_no_sys_or_secret_logs(self):
        self.stage();self.assertNotIn('PLACEHOLDER_ONLY',repr(self.mock.calls))
        with self.assertRaises(Rejected):self.adapter._request('POST','/v1/sys/mounts/kv',{})
if __name__=='__main__':unittest.main()
