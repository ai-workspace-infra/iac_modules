# UAT DNS reconciliation owner

Owner: IaC Modules. Caller: Toolkit Selfhost Orchestrator.

Inputs: runtime-only `CLOUDFLARE_DNS_API_TOKEN`, `DEPLOY_ENV=uat`,
`SOURCE_DOMAIN_BASE`, `TARGET_DOMAIN_BASE`, `TARGET_DOMAINS`,
`GITOPS_ROUTING_CONFIG` (rendered EdgeRoutingConfig), and `CMDB_FILE`.
CMDB is supplied by the exact caller run; metadata is ignored when selecting
host objects. Exactly one Web SaaS host is required outside Agent Proxy-only mode.

Only the declared UAT zone and mode-qualified records are reconciled. Existing
canonical entries retain their current owner. Outputs are sanitized per-record
actions and a summary; any provider/identity/validation failure fails the caller.
The operation is idempotent. The original Toolkit executor remains frozen until
the fixed owner ref passes live UAT, then the old copy and its tests are removed.

Tests: `bash scripts/pipeline/tests/platform_ops_uat_dns_target_records_test.sh`
and `bash scripts/pipeline/tests/platform_ops_agent_proxy_uat_dns_test.sh`.
