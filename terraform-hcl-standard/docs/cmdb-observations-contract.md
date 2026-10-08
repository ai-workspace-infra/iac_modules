# Provider observations contract (`cmdb.observations.v1`)

This contract represents observed provider inventory and collection completeness.
It is distinct from `cmdb.v1`, which remains the deploy-time Terraform output
consumed by the existing Playbooks inventory plugin.

`scripts/cmdb_observations_v1.py` validates a normalized envelope and derives a
canonical identity from provider, account, project, resource kind, and native
resource ID. It deliberately makes no provider calls and writes no database.
Cloud API adapters and PostgreSQL persistence are follow-on integrations; a
validated fixture/artifact is not evidence of live inventory or a completed
collector.

```json
{
  "schema_version": "cmdb.observations.v1",
  "run": {
    "run_id": "opaque-run-id",
    "collector": "gcp-compute",
    "owner_sha": "immutable-owner-commit",
    "scope": "shared",
    "account_ref": "gcp-org-ref",
    "project_ref": "open-platform-shared-510113",
    "region_ref": "asia-east1",
    "started_at": "2026-10-08T00:00:00Z",
    "completed_at": "2026-10-08T00:00:10Z",
    "outcome": "success",
    "scope_complete": true
  },
  "observations": [
    {
      "provider": "gcp",
      "account_ref": "gcp-org-ref",
      "project_ref": "open-platform-shared-510113",
      "resource_kind": "compute",
      "native_resource_id": "projects/.../zones/.../instances/123456",
      "region": "asia-east1",
      "scope": "shared",
      "name": "example",
      "provider_state": "running",
      "provider_state_raw": "RUNNING",
      "source": "provider_api",
      "observed_at": "2026-10-08T00:00:10Z",
      "attributes": {"machine_type": "e2-medium"}
    }
  ]
}
```

## Invariants

- A successful run must have a completion timestamp and `scope_complete: true`.
  Partial/failed runs must remain incomplete; zero observations are acceptable
  only when the provider adapter proves the declared scope was completely read.
- Resource keys use native provider identity, not mutable name or IP. Shared
  resources remain `scope: shared`; unresolved environment mappings remain
  `unknown` rather than being inferred as production.
- `provider_state_raw` preserves provider wording. `provider_state` is a
  normalized state used for summaries and never replaces the raw value.
- `source` is `provider_api` or `external_inventory`. UCloud lightweight-host
  data without a verified API remains external inventory with its own timestamp
  and TTL, never mislabeled as API-confirmed.
- Arbitrary credentials, user data, startup scripts, and environment values are
  prohibited. Provider adapters must filter payloads before creating
  `attributes`; the validator rejects secret-like keys as a second guard.
- A partial/failed run cannot prove resources were deleted. Deletion requires
  later complete runs and provider-specific confirmation in persistence logic.

Cloud APIs, runtime identities, PostgreSQL transactional upsert/locking,
retention, and Toolkit orchestration are not implemented by this contract.
