"""Injected KVv2 interface; mock transport only. No network/token/mount provisioning."""
from dataclasses import dataclass, field
from typing import Protocol
import copy
import re
from database_contract import require, ident, shape, secret_ref, Rejected

@dataclass(frozen=True)
class Response:
    status: int
    data: object = field(default=None,repr=False)

class Transport(Protocol):
    fixture_only: bool
    def request(self, method, path, auth_ref, body=None): ...

@dataclass(frozen=True)
class Staged:
    operation_id: str
    active_path: str
    staging_path: str
    staging_version: int
    expected_version: int

class VaultAdapter:
    def __init__(self, transport, auth_ref):
        require(getattr(transport,'fixture_only',False) is True,'real_vault_access_disabled')
        require(type(auth_ref) is str and re.fullmatch(r'oidc/[A-Za-z0-9_/-]+',auth_ref),'oidc_ref_required')
        self.transport,self.auth_ref=transport,auth_ref
    def _request(self,method,path,body=None):
        # No sys/mounts, policy, token, delete, destroy, undelete or automatic migration API.
        require(method in ('GET','POST') and path.startswith('/v1/kv/'),'vault_api_not_allowed')
        try: response=self.transport.request(method,path,self.auth_ref,body)
        except TimeoutError:raise Rejected('vault_timeout_outcome_unknown') from None
        except Exception:raise Rejected('vault_transport_failed') from None
        require(type(response) is Response,'invalid_vault_response')
        if response.status in (401,403):raise Rejected('vault_forbidden')
        require(response.status in (200,404),'vault_response_failed')
        return response
    def _data(self,path):
        r=self._request('GET','/v1/kv/data/'+path)
        if r.status==404:return None
        require(type(r.data) is dict and set(r.data)=={'version','value'},'invalid_vault_data')
        return r.data
    def metadata(self,ref):
        # Compatibility reader NEVER fetches data or validates presence of a secret field.
        shape(ref,'apiVersion mount path field')
        require(ref['apiVersion']=='LegacySecretRef/v1' and ref['mount']=='kv','invalid_legacy_ref')
        require(ref['path'] in ('prod/databases','prod/database-upgrade') and ref['field']=='PROD_SUPABASE_READONLY_DSN','legacy_ref_not_allowlisted')
        r=self._request('GET','/v1/kv/metadata/'+ref['path'])
        if r.status==404:return {'apiVersion':'SecretMetadataReceipt/v1','exists':False,'current_version':None,'field_presence':'not_checked_metadata_only'}
        require(type(r.data) is dict and type(r.data.get('current_version')) is int,'invalid_metadata')
        return {'apiVersion':'SecretMetadataReceipt/v1','exists':True,'current_version':r.data['current_version'],'field_presence':'not_checked_metadata_only'}
    def stage(self,identity,purpose,ref,operation_id,payload):
        secret_ref(ref,identity,purpose);ident(operation_id)
        require(identity['env']=='fixture','new_writer_fixture_only')
        shape(payload,'dsn');require(type(payload['dsn']) is str and len(payload['dsn'])>0,'invalid_secret_payload')
        active=ref['path'];staging=active+'/_staging/'+operation_id
        value={'operation_id':operation_id,'dsn':payload['dsn']}
        existing=self._data(staging)
        if existing is not None:
            require(existing['value']==value,'staging_operation_conflict')
            return Staged(operation_id,active,staging,existing['version'],ref['expected_version'])
        try:
            r=self._request('POST','/v1/kv/data/'+staging,{'options':{'cas':0},'data':value})
            require(r.status==200,'staging_write_failed')
            version=r.data['version']
        except Rejected as exc:
            if str(exc) not in ('vault_timeout_outcome_unknown','vault_response_failed'):raise
            recovered=self._data(staging)
            require(recovered is not None and recovered['value']==value,'staging_write_outcome_unknown')
            version=recovered['version']
        return Staged(operation_id,active,staging,version,ref['expected_version'])
    def promote(self,staged,verify):
        require(type(staged) is Staged and staged.active_path.startswith('fixture/databases/'),'invalid_staging_handle')
        ident(staged.operation_id)
        require(re.fullmatch(r'fixture/databases/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/(dba|runtime|ddl_migrator|readonly_export|readonly_audit|monitor)',staged.active_path) and staged.staging_path==staged.active_path+'/_staging/'+staged.operation_id,'invalid_staging_scope')
        require(type(staged.expected_version) is int and staged.expected_version>=0 and type(staged.staging_version) is int and staged.staging_version>0,'invalid_staging_version')
        source=self._data(staged.staging_path)
        require(source is not None and source['version']==staged.staging_version and source['value'].get('operation_id')==staged.operation_id,'staging_changed')
        current=self._data(staged.active_path)
        if current is not None and current['version']==staged.expected_version+1 and current['value']==source['value']:
            return {'operation_id':staged.operation_id,'status':'active','version':current['version']}
        require((current['version'] if current else 0)==staged.expected_version,'active_cas_conflict')
        try:valid=verify({'dsn':source['value']['dsn']}) is True
        except Exception:raise Rejected('staging_verification_failed') from None
        require(valid,'staging_verification_failed')
        try:
            r=self._request('POST','/v1/kv/data/'+staged.active_path,{'options':{'cas':staged.expected_version},'data':source['value']})
            require(r.status==200,'active_write_failed')
            version=r.data['version']
        except Rejected as exc:
            if str(exc) not in ('vault_timeout_outcome_unknown','vault_response_failed'):raise
            recovered=self._data(staged.active_path)
            require(recovered is not None and recovered['version']==staged.expected_version+1 and recovered['value']==source['value'],'active_write_outcome_unknown')
            version=recovered['version']
        return {'operation_id':staged.operation_id,'status':'active','version':version}

class MockVaultTransport:
    fixture_only=True
    def __init__(self):self.store={};self.calls=[];self.faults={}
    def inject(self,method,path,*faults):self.faults[(method,path)]=list(faults)
    def request(self,method,path,auth_ref,body=None):
        # Calls retain ONLY metadata, not payloads or real tokens.
        self.calls.append((method,path,auth_ref))
        queue=self.faults.get((method,path),[]);fault=queue.pop(0) if queue else None
        if fault=='timeout_before':raise TimeoutError('redacted')
        if type(fault) is int:return Response(fault)
        if path.startswith('/v1/kv/metadata/') and method=='GET':
            key=path[len('/v1/kv/metadata/'):];entry=self.store.get(key)
            response=Response(200,{'current_version':entry['version']}) if entry else Response(404)
        elif path.startswith('/v1/kv/data/'):
            key=path[len('/v1/kv/data/'):];entry=self.store.get(key)
            if method=='GET':response=Response(200,copy.deepcopy(entry)) if entry else Response(404)
            elif method=='POST':
                expected=body['options']['cas'];actual=entry['version'] if entry else 0
                if expected!=actual:response=Response(400)
                else:
                    self.store[key]={'version':actual+1,'value':copy.deepcopy(body['data'])};response=Response(200,{'version':actual+1})
            else:response=Response(405)
        else:response=Response(405)
        if fault=='timeout_after':raise TimeoutError('redacted')
        return response

class DynamicCredentials(Protocol):
    # Future interface only. No implementation, lease acquisition or ready claim.
    def acquire(self, role_ref, operation_id): ...
    def revoke(self, lease_ref): ...
