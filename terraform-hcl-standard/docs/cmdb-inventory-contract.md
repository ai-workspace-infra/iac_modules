# IaC → CMDB → Playbooks contract

GitOps resource declarations remain the desired state. The provider-specific
IaC renderer selects the cloud provider, applies the resources, and then reads
only Terraform runtime outputs to publish a `cmdb.json` artifact.

The artifact uses `schema_version: cmdb.v1` and has this canonical shape:

```json
{
  "schema_version": "cmdb.v1",
  "environment": "prod",
  "cloud_provider": "gcp-cloud",
  "project_id": "open-platform-prod",
  "source_resources": ["resources/.../web-saas.yaml"],
  "hosts": {
    "web-saas-prod": {
      "ip": "203.0.113.10",
      "private_ip": "10.0.0.10",
      "resource_id": "provider-native-resource-id",
      "ansible_user": "os-login-user",
      "groups": ["web_saas"],
      "host_vars": {}
    }
  }
}
```

`hosts` is the canonical SSH-capable compute consumer interface (`vm` and `k3s_node`).
Serverless resources (Cloud Run, Cloudflare Workers/Pages, Supabase, etc.) allow
`ssh_host: null` and `primary_ip: null` and are emitted under `serverless_resources`
without fabricating SSH hosts or placeholder IPs. All resources (both compute and
serverless) are indexed and deduplicated idempotently in `resource_index` by the
authoritative `resource_key`:

```
{provider}:{account_or_project}:{region}:{resource_id}
```

Each normalized resource record in `resource_index` carries:
- `resource_key`: `{provider}:{account_or_project}:{region}:{resource_id}`
- `runtime_form`: `vm` | `k3s_node` | `serverless`
- Extended dimensions: `environment`, `service`, `cluster`, `namespace`, `node`
- Timestamps: `observed_at` and `last_observed_at` (ISO-8601 UTC)
- Status: `active` | `unobserved` | `collection_failed` | `deleted`

Provider renderers keep legacy top-level host keys during the migration so existing
receipts and read-only data-operation helpers continue to work. Playbooks consumes the
artifact through `inventory/terraform_cmdb.py`; it does not read Terraform
state directly and it rejects unknown CMDB schema versions.

The required flow is:

1. GitOps declares environment, provider, resource shape, inventory groups and
   host variables.
2. The matching IaC module renders and applies that declaration.
3. The IaC module combines declaration metadata with non-secret Terraform
   runtime facts and writes `cmdb.json`.
4. Playbooks receives that CMDB as `AI_WORKSPACE_CMDB_JSON` or `CMDB_FILE` and
   executes against the declared host identity.

Secrets, private keys and database contents are not part of the CMDB.
