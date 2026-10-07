from pathlib import Path
import copy,json,unittest
from database_contract import Rejected
from roles_adapter import make_plan,RoleExecutor,quote_identifier

class Resolver:
    fixture_only=True
    def password(self,purpose,ref):return 'PLACEHOLDER_ONLY'

class Driver:
    fixture_only=True
    def __init__(self,snapshot):self.state=copy.deepcopy(snapshot);self.writes=[];self.committed=False;self.rolled_back=False;self.fail_at=None
    def snapshot(self,*args):return copy.deepcopy(self.state)
    def begin(self):self.writes=[]
    def execute(self,sql,params=()):
        if self.fail_at is not None and len(self.writes)==self.fail_at:raise RuntimeError('PLACEHOLDER_ONLY secret error')
        self.writes.append((sql,params))
    def create_login(self,sql,password):self.execute(sql,('<OPAQUE>',))
    def assert_secret_logging_disabled(self):pass
    def verify(self,*args):return True
    def commit(self):self.committed=True
    def rollback(self):self.writes=[];self.rolled_back=True

class RoleTests(unittest.TestCase):
    def setUp(self):
        self.spec=json.loads((Path(__file__).parent/'example.json').read_text());self.scope={'apiVersion':'DatabaseGrantScope/v1','schemas':['example_business']}
        self.snapshot={'lookup_status':200,'role_states':{},'credential_available':{}}
    def test_plan_has_no_password_or_business_ddl(self):
        p=make_plan(self.spec,self.scope,self.snapshot);out=json.dumps(p.public())
        for value in ('PLACEHOLDER_ONLY','PASSWORD','CREATE TABLE','CREATE DATABASE','DROP ','ALTER USER'):self.assertNotIn(value,out)
        self.assertEqual(sum(a.kind=='create_login' for a in p.actions),6)
        self.assertEqual(sum(a.kind=='create_owner' for a in p.actions),1)
        self.assertIn('WITH INHERIT FALSE, SET TRUE',out)
    def test_identifier_rejection(self):
        for value in ['a"; DROP ROLE x;--','x\x00','pg_catalog.bad','x'*64]:
            with self.assertRaises(Rejected):quote_identifier(value)
        self.assertEqual(quote_identifier('valid-hyphen'),'"valid-hyphen"')
    def test_existing_missing_and_unsafe_roles(self):
        for state in [{'login':True,'elevated':False,'memberships':[]},{'login':True,'elevated':True,'memberships':[]},{'login':True,'elevated':False,'memberships':['unapproved']}]:
            self.snapshot['role_states']['example_runtime']=state
            with self.assertRaises(Rejected):make_plan(self.spec,self.scope,self.snapshot)
    def test_existing_verified_does_not_rotate(self):
        self.snapshot['role_states']['example_runtime']={'login':True,'elevated':False,'memberships':[]};self.snapshot['credential_available']['runtime']=True
        p=make_plan(self.spec,self.scope,self.snapshot)
        self.assertFalse(any(a.role=='example_runtime' and a.kind=='create_login' for a in p.actions))
        self.assertFalse(any('PASSWORD' in a.sql for a in p.actions))
    def test_denied_lookup_and_operations(self):
        for status in (403,401,500,0):
            self.snapshot['lookup_status']=status
            with self.assertRaises(Rejected):make_plan(self.spec,self.scope,self.snapshot)
        self.snapshot['lookup_status']=200;self.spec['operation']='rotate';self.spec['safety']['allow_rotation']=True
        with self.assertRaises(Rejected):make_plan(self.spec,self.scope,self.snapshot)
    def test_execute_atomic_and_errors_redacted(self):
        p=make_plan(self.spec,self.scope,self.snapshot);d=Driver(self.snapshot)
        result=RoleExecutor(d,Resolver()).execute(self.spec,self.scope,p)
        self.assertTrue(d.committed);self.assertNotIn('PLACEHOLDER_ONLY',json.dumps(result))
        d=Driver(self.snapshot);d.fail_at=5
        with self.assertRaisesRegex(Rejected,'^role_transaction_failed$'):RoleExecutor(d,Resolver()).execute(self.spec,self.scope,p)
        self.assertTrue(d.rolled_back);self.assertFalse(d.committed);self.assertEqual(d.writes,[])
    def test_plan_drift_and_real_access_disabled(self):
        p=make_plan(self.spec,self.scope,self.snapshot);d=Driver(self.snapshot);d.state['role_states']['example_owner']={'login':False,'elevated':False,'memberships':[]}
        with self.assertRaisesRegex(Rejected,'plan_drift'):RoleExecutor(d,Resolver()).execute(self.spec,self.scope,p)
        d=Driver(self.snapshot);d.fixture_only=False
        with self.assertRaisesRegex(Rejected,'real_access_disabled'):RoleExecutor(d,Resolver()).execute(self.spec,self.scope,p)
    def test_inspect_has_no_write(self):
        self.spec['operation']='inspect';self.spec['mode']='existing_external';self.spec['safety']['explicit_adoption']=False
        p=make_plan(self.spec,self.scope,self.snapshot);d=Driver(self.snapshot)
        RoleExecutor(d,Resolver()).execute(self.spec,self.scope,p);self.assertEqual(d.writes,[])
    def test_scope_and_observation_types_rejected(self):
        self.scope['schemas']=[{}]
        with self.assertRaises(Rejected):make_plan(self.spec,self.scope,self.snapshot)
        self.scope['schemas']=['example_business'];self.snapshot['credential_available']['runtime']='PLACEHOLDER_ONLY'
        with self.assertRaises(Rejected):make_plan(self.spec,self.scope,self.snapshot)
    def test_create_new_cannot_adopt_existing_role_target(self):
        self.spec['mode']='create_new';self.spec['safety']['explicit_adoption']=False
        with self.assertRaises(Rejected):make_plan(self.spec,self.scope,self.snapshot)
    def test_secret_resolution_error_redacted(self):
        class BrokenResolver(Resolver):
            def password(self,*args):raise RuntimeError('PLACEHOLDER_ONLY')
        p=make_plan(self.spec,self.scope,self.snapshot)
        with self.assertRaisesRegex(Rejected,'^credential_resolution_failed$'):RoleExecutor(Driver(self.snapshot),BrokenResolver()).execute(self.spec,self.scope,p)
    def test_system_scope_rejected(self):
        self.scope['schemas']=['pg_catalog']
        with self.assertRaises(Rejected):make_plan(self.spec,self.scope,self.snapshot)
if __name__=='__main__':unittest.main()
