"""Deterministic role/grant plans and fixture-only transactional execution.

No connection factory, Vault client, shell, secret logging or production execution.
Passwords are resolved only by the injected fixture resolver and never enter plans.
"""
from dataclasses import dataclass
import hashlib
import json
from database_contract import validate, require, ident, shape, lookup_exists, receipt, Rejected

@dataclass(frozen=True)
class Action:
    kind: str
    sql: str
    role: str = ''
    purpose: str = ''

@dataclass(frozen=True)
class RolePlan:
    operation_id: str
    actions: tuple
    digest: str
    def public(self):
        return {'apiVersion':'DatabaseRolePlan/v1','operation_id':self.operation_id,
                'digest':self.digest,'actions':[{'kind':a.kind,'sql':a.sql,'role':a.role,'purpose':a.purpose} for a in self.actions]}

SAFE_FLAGS='NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT'

def quote_identifier(value):
    ident(value)
    return '"'+value.replace('"','""')+'"'

def check_scope(scope):
    shape(scope,'apiVersion schemas')
    require(scope['apiVersion']=='DatabaseGrantScope/v1', 'invalid_grant_scope')
    require(type(scope['schemas']) is list and 0<len(scope['schemas'])<=20,'explicit_schemas_required')
    for schema in scope['schemas']:
        ident(schema); require(schema not in ('pg_catalog','information_schema') and not schema.startswith('pg_'),'system_schema_rejected')
    require(len(scope['schemas'])==len(set(scope['schemas'])),'duplicate_schema')

def make_plan(spec, scope, snapshot):
    validate(spec);check_scope(scope)
    shape(snapshot,'lookup_status role_states credential_available')
    exists=lookup_exists(snapshot['lookup_status'])
    require(exists,'engine_provision_required_first')
    require(type(snapshot['role_states']) is dict and type(snapshot['credential_available']) is dict,'invalid_role_snapshot')
    names={r['name'] for r in spec['roles']}
    purposes={r['purpose'] for r in spec['roles'] if r['login']}
    require(set(snapshot['role_states']) <= names and set(snapshot['credential_available']) <= purposes,'unknown_snapshot_role')
    require(all(type(v) is bool for v in snapshot['credential_available'].values()),'invalid_credential_observation')
    for state in snapshot['role_states'].values():
        shape(state,'login elevated memberships')
        require(type(state['login']) is bool and type(state['elevated']) is bool and type(state['memberships']) is list,'invalid_role_state')
        for member in state['memberships']: ident(member)
    require(spec['operation'] in ('inspect','roles'),'role_operation_only')
    if spec['operation']=='inspect':
        actions=[]
    else:
        require(spec['mode']=='adopt_existing','role_stage_requires_explicit_existing_target')
        roles={r['purpose']:r for r in spec['roles']};actions=[]
        for role in spec['roles']:
            name,purpose=role['name'],role['purpose']; state=snapshot['role_states'].get(name)
            if state is not None:
                shape(state,'login elevated memberships')
                require(type(state['login']) is bool and type(state['elevated']) is bool and type(state['memberships']) is list,'invalid_role_state')
                require(not state['elevated'] and state['login']==role['login'],'unsafe_existing_role')
                allowed={roles['owner']['name']} if purpose in ('dba','ddl_migrator') else ({'pg_monitor'} if purpose=='monitor' else set())
                require(all(type(x) is str and x in allowed for x in state['memberships']),'unexpected_existing_membership')
                if role['login']:
                    require(snapshot['credential_available'].get(purpose) is True,'existing_role_missing_credential')
            else:
                # Password is an opaque resolver parameter, not part of this public SQL plan.
                actions.append(Action('create_login' if role['login'] else 'create_owner',
                                      'CREATE ROLE '+quote_identifier(name)+' '+('LOGIN' if role['login'] else 'NOLOGIN')+' '+SAFE_FLAGS,
                                      name,purpose))
            if state is not None:
                actions.append(Action('statement','ALTER ROLE '+quote_identifier(name)+' '+SAFE_FLAGS))
        owner=quote_identifier(roles['owner']['name'])
        for purpose in ('dba','ddl_migrator'):
            actions.append(Action('statement','GRANT '+owner+' TO '+quote_identifier(roles[purpose]['name'])+' WITH INHERIT FALSE, SET TRUE'))
        actions.append(Action('statement','GRANT pg_monitor TO '+quote_identifier(roles['monitor']['name'])+' WITH INHERIT TRUE, SET FALSE'))
        db=quote_identifier(spec['identity']['database'])
        for role in spec['roles']:
            if role['login']:actions.append(Action('statement','GRANT CONNECT ON DATABASE '+db+' TO '+quote_identifier(role['name'])))
        for schema in scope['schemas']:
            qs=quote_identifier(schema)
            # Explicit schemas only; no schema creation, ownership transfer, PUBLIC revoke or business DDL.
            actions.append(Action('statement','GRANT USAGE, CREATE ON SCHEMA '+qs+' TO '+owner))
            for purpose in ('runtime','readonly_export','readonly_audit'):
                qr=quote_identifier(roles[purpose]['name'])
                actions.append(Action('statement','GRANT USAGE ON SCHEMA '+qs+' TO '+qr))
                tables='SELECT, INSERT, UPDATE, DELETE' if purpose=='runtime' else 'SELECT'
                actions.append(Action('statement','GRANT '+tables+' ON ALL TABLES IN SCHEMA '+qs+' TO '+qr))
                seq='USAGE, SELECT' if purpose=='runtime' else 'SELECT'
                actions.append(Action('statement','GRANT '+seq+' ON ALL SEQUENCES IN SCHEMA '+qs+' TO '+qr))
                # Covers future objects only when migratectl explicitly SET ROLE owner.
                actions.append(Action('statement','ALTER DEFAULT PRIVILEGES FOR ROLE '+owner+' IN SCHEMA '+qs+' GRANT '+tables+' ON TABLES TO '+qr))
                actions.append(Action('statement','ALTER DEFAULT PRIVILEGES FOR ROLE '+owner+' IN SCHEMA '+qs+' GRANT '+seq+' ON SEQUENCES TO '+qr))
    body={'spec':spec,'scope':scope,'snapshot':snapshot,'actions':[a.__dict__ for a in actions]}
    digest=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return RolePlan(spec['operation_id'],tuple(actions),digest)

class RoleExecutor:
    def __init__(self, driver, resolver):
        self.driver,self.resolver=driver,resolver

    def execute(self, spec, scope, approved_plan):
        validate(spec)
        require(spec['identity']['env']=='fixture' and getattr(self.driver,'fixture_only',False) is True and getattr(self.resolver,'fixture_only',False) is True,'real_access_disabled')
        require(type(approved_plan) is RolePlan,'reviewed_plan_required')
        # Snapshot must come from driver; stale/fabricated plans are rejected before role writes.
        try: snapshot=self.driver.snapshot(spec,self.resolver)
        except Exception: raise Rejected('role_snapshot_failed') from None
        plan=make_plan(spec,scope,snapshot)
        require(plan==approved_plan,'plan_drift')
        if spec['operation']=='inspect':return receipt(spec,'offline_pass',{'contract':'pass','permissions':'not_run'})
        credentials={}
        for action in plan.actions:
            if action.kind=='create_login':
                ref=next(r['dsn_secret_ref'] for r in spec['roles'] if r['name']==action.role)
                try: credential=self.resolver.password(action.purpose,ref)
                except Exception: raise Rejected('credential_resolution_failed') from None
                require(type(credential) is str and len(credential)>0 and '\x00' not in credential,'new_role_credential_missing')
                credentials[action.role]=credential
        try:
            self.driver.begin()
            # Cluster roles are global: fixture serializes all role adapters, not just one database.
            self.driver.execute('SELECT pg_advisory_xact_lock($1::bigint)',('73017001',))
            require(make_plan(spec,scope,self.driver.snapshot(spec,self.resolver))==plan,'plan_drift')
            self.driver.assert_secret_logging_disabled()
            for action in plan.actions:
                if action.kind=='create_login':self.driver.create_login(action.sql,credentials[action.role])
                else:self.driver.execute(action.sql)
            require(self.driver.verify(spec,scope) is True,'role_verification_failed')
            self.driver.commit()
        except Exception:
            try: self.driver.rollback()
            except Exception: pass
            # Never expose driver exceptions, SQL, parameters or secrets in errors/receipts.
            raise Rejected('role_transaction_failed') from None
        finally:
            credentials.clear() # Python strings are not guaranteed to be zeroized.
        return receipt(spec,'offline_pass',{'contract':'pass','permissions':'pass','migration':'not_run','source_readonly':'not_run'})
