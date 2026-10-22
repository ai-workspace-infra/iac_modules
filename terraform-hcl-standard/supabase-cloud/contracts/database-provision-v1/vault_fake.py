"""In-memory lifecycle fixture only; not a real Vault implementation."""
from database_contract import Rejected, require

class FakeVault:
    def __init__(self):
        self.active = {}
        self.staging = {}

    def stage(self, operation_id, path, payload, expected_version):
        require(path.startswith('fixture/databases/'), 'fixture_scope_only')
        require(type(expected_version) is int and expected_version >= 0, 'invalid_cas')
        require(type(payload) is dict and set(payload) == {'dsn'}, 'invalid_payload')
        request=(path, payload.copy(), expected_version)
        if operation_id in self.staging:
            require(self.staging[operation_id] == request, 'operation_conflict')
            return
        require(self.active.get(path, (0,None))[0] == expected_version, 'cas_conflict')
        self.staging[operation_id]=request

    def promote(self, operation_id, verify):
        require(operation_id in self.staging, 'unknown_operation')
        path, payload, expected=self.staging[operation_id]
        version, current=self.active.get(path,(0,None))
        if version == expected+1 and current == (operation_id,payload): return version
        require(version == expected, 'cas_conflict')
        require(verify(payload) is True, 'verification_failed')
        self.active[path]=(expected+1,(operation_id,payload.copy()))
        return expected+1
