# AI Aggregator VPS provider contract

The logical node IDs are defined by GitOps and must remain stable across
providers:

- `gateway-01`
- `cpa-codex-01`
- `cpa-codex-02`
- `cpa-claude-01`
- `cpa-grok-01`

Each provider adapter exposes the same runtime facts to CMDB:
`provider`, `environment`, `role`, `lifecycle`, `instance_id`, `public_ip`,
`private_ip`, `region_or_zone`, `os`, `architecture`, and `expires_at` for
ephemeral instances.

AWS is the first executable UAT adapter: ARM64 Spot instances with a
60-minute cloud-init TTL guard. Vultr and GCP provide the same declarative
shape for future CPA/Gateway placement. Production nodes remain external
persistent hosts and are not imported into Terraform state by v1.

Provider credentials and state backend credentials are supplied through Vault
or CI OIDC; this contract contains no secret values.
