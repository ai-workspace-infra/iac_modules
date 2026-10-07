# Pipeline Provider execution migration

This change owns the migrated Vultr preflight, existing-target CMDB renderer, SIT DNS reconciliation, SMTP Secret Manager synchronization, Cloud Run/Cloudflare deployment, and UAT cleanup modules. Toolkit selects/authenticates and invokes a reviewed immutable owner SHA; GitOps declares targets and cleanup policy.

Vultr preflight emits the resolved instance ID for all downstream operations and rejects ambiguous resolution. An existing external target produces an explicit-target inventory without fabricated Provider ID, size, region or state. SMTP writes must converge to Vault values; configured-secret failures cannot return success.

UAT cleanup is constrained to the declared UAT project/region/service allowlist. It requires a successful inventory before deletion, propagates failures, and verifies absence afterward. Plan receipts have accepted=false. The checked-in GitOps policy is disabled pending review/UAT; no image pruning, database deletion, or PROD cleanup is implemented.

Deployment receipts bind owner SHA, environment, release, run/attempt, operation and target. They prove the Provider command completed, not live business or authenticated service acceptance.

Validation: 8 mock Provider cleanup cases, including disabled/PROD scope, query/deletion failure and nonconvergence; Bash syntax and action YAML. No cloud mutation or live UAT acceptance was performed. Existing Toolkit executors remain frozen pending exact owner/caller verification and retirement.
