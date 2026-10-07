"""DatabaseProvisionSpec/v1: offline, non-secret boundary. No network or secret reads."""
import re

class Rejected(ValueError):
    pass

def require(test, code):
    if not test:
        raise Rejected(code)

def shape(value, keys):
    require(type(value) is dict and set(value) == set(keys.split()), 'invalid_shape')

def ident(value):
    require(type(value) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,63}', value), 'invalid_identity')

def secret_ref(ref, identity, purpose):
    shape(ref, 'kind mount path field expected_version')
    require(ref['kind'] == 'kv_v2' and ref['mount'] == 'kv' and ref['field'] == 'dsn', 'invalid_secret_ref')
    require(type(ref['expected_version']) is int and ref['expected_version'] >= 0, 'invalid_cas')
    expected = '/'.join([identity['env'], 'databases', identity['instance'], identity['database'], purpose])
    require(ref['path'] == expected, 'secret_scope_mismatch')

def validate(spec):
    shape(spec, 'apiVersion identity backend mode operation operation_id repository_shas tls roles safety vault')
    require(spec['apiVersion'] == 'DatabaseProvisionSpec/v1', 'invalid_version')
    shape(spec['identity'], 'env instance database')
    for value in spec['identity'].values(): ident(value)
    ident(spec['operation_id'])
    require(spec['backend'] in ('self_managed_postgresql', 'supabase_cloud'), 'invalid_backend')
    require(spec['mode'] in ('create_new', 'adopt_existing', 'existing_external'), 'invalid_mode')
    require(spec['operation'] in ('inspect', 'provision', 'roles', 'rotate', 'engine_reconfigure', 'rebuild', 'delete', 'cutover'), 'invalid_operation')
    shape(spec['repository_shas'], 'playbooks iac_modules')
    for sha in spec['repository_shas'].values():
        require(type(sha) is str and re.fullmatch('[0-9a-f]{40}', sha), 'invalid_sha')
    shape(spec['tls'], 'mode ca_ref')
    require(spec['tls']['mode'] == 'verify-full', 'tls_required')
    require(type(spec['tls']['ca_ref']) is str and re.fullmatch(r'[A-Za-z0-9_/-]{1,120}', spec['tls']['ca_ref']), 'invalid_ca_ref')
    shape(spec['safety'], 'strict_no_secret_state allow_rotation allow_rebuild allow_delete allow_cutover allow_engine_change explicit_adoption')
    require(all(type(v) is bool for v in spec['safety'].values()), 'invalid_switch')
    required_switch = {'rotate':'allow_rotation','rebuild':'allow_rebuild','delete':'allow_delete','cutover':'allow_cutover','engine_reconfigure':'allow_engine_change'}
    for op, switch in required_switch.items():
        require(spec['safety'][switch] == (spec['operation'] == op), 'operation_switch_mismatch')
    require(spec['safety']['explicit_adoption'] == (spec['mode'] == 'adopt_existing'), 'explicit_adoption_required')
    require(spec['mode'] != 'existing_external' or spec['operation'] == 'inspect', 'external_is_read_only')
    shape(spec['vault'], 'auth_ref mount publication')
    require(spec['vault']['mount'] == 'kv' and spec['vault']['publication'] == 'staging_validate_active', 'invalid_vault')
    require(type(spec['vault']['auth_ref']) is str and re.fullmatch(r'oidc/[A-Za-z0-9_/-]+', spec['vault']['auth_ref']), 'short_lived_oidc_required')
    require(type(spec['roles']) is list and len(spec['roles']) == 7, 'required_roles')
    purposes=set()
    for role in spec['roles']:
        shape(role, 'name purpose login dsn_secret_ref')
        ident(role['name']); purpose=role['purpose']
        require(type(purpose) is str and purpose in ('dba','runtime','ddl_migrator','readonly_export','readonly_audit','monitor','owner') and purpose not in purposes, 'invalid_purpose')
        purposes.add(purpose)
        require(type(role['login']) is bool and role['login'] == (purpose != 'owner'), 'invalid_login')
        if purpose == 'owner': require(role['dsn_secret_ref'] is None, 'owner_has_no_dsn')
        else: secret_ref(role['dsn_secret_ref'], spec['identity'], purpose)
    require(len({r['name'] for r in spec['roles']}) == 7, 'distinct_roles_required')
    return spec

def lookup_exists(status):
    require(type(status) is int and status in (200,404), 'lookup_not_authoritative')
    return status == 200

def preflight(spec, observations):
    validate(spec)
    shape(observations, 'lookup_status existing_roles credential_available')
    exists=lookup_exists(observations['lookup_status'])
    require(type(observations['existing_roles']) is list and all(type(x) is str for x in observations['existing_roles']), 'invalid_observation')
    require(type(observations['credential_available']) is dict and all(type(v) is bool for v in observations['credential_available'].values()), 'invalid_observation')
    require(not (spec['mode'] == 'create_new' and exists), 'already_exists')
    require(not (spec['mode'] != 'create_new' and not exists), 'existing_target_missing')
    for role in spec['roles']:
        if role['login'] and role['name'] in observations['existing_roles']:
            require(observations['credential_available'].get(role['purpose']) is True, 'existing_role_missing_credential')
    if spec['backend'] == 'supabase_cloud' and spec['operation'] != 'inspect' and spec['safety']['strict_no_secret_state']:
        raise Rejected('provider_secret_state_unsupported')
    return True

def receipt(spec, status, checks):
    validate(spec)
    require(status in ('offline_pass','blocked','pending_production'), 'invalid_status')
    require(type(checks) is dict and set(checks) <= {'contract','vault_mock','permissions','migration','source_readonly'}, 'invalid_checks')
    require(all(v in ('pass','fail','not_run') for v in checks.values()), 'invalid_check_result')
    # Build only from an allowlist. No provider errors, endpoint, credentials or free text.
    return {'apiVersion':'DatabaseProvisionReceipt/v1', 'identity':spec['identity'].copy(),
            'backend':spec['backend'], 'mode':spec['mode'], 'operation':spec['operation'],
            'operation_id':spec['operation_id'], 'repository_shas':spec['repository_shas'].copy(),
            'status':status, 'checks':checks.copy()}
