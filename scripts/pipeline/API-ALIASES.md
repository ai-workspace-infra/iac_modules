# Accounts/Billing API DNS owner

The composite action `.github/actions/cloudflare-api-aliases` owns provider changes only. Its caller must pin an exact reviewed IaC commit, authenticate through its environment OIDC/Vault role, deploy Edge Gateway first, and provide the rendered fixed-SHA GitOps plan and exact gateway commit. Secrets remain in environment variables and never enter action inputs or checkpoints.

The explicit `api_alias_mode: worker-routes-cname` contract is required. Legacy declarations produce no DNS changes. Only the two canonical Accounts/Billing aliases and their qualified Serverless Worker domains are in scope. Brand, Console, Pages, unrelated records, and foreign Worker domains are preserved. All three Worker revisions, modes and four origins and all canonical boundary Routes must match the plan before mutations.

A private checkpoint is written before mutations. On provider failure this owner restores the two API aliases if their state has not changed concurrently; it refuses to overwrite another operator's changes. Re-running an already reconciled plan has no provider writes. A fresh checkpoint path is required per attempt. Do not publish checkpoints: provider record identifiers and private configuration remain operational data.

**Caller prerequisite:** any writer change must already have a trusted, fresh full-business equality and single-writer receipt. This DNS owner does not generate or validate database evidence and does not probe HTTP services. Its sanitized success receipt explicitly sets `business_verified=false`; Edge Gateway owns public HTTP verification after provider convergence.

The fixed-SHA reusable workflow `.github/workflows/cloudflare-serverless-domains.yml` is the Toolkit Serverless publisher's new provider owner. It validates the caller, immutable GitOps revision and environment before OIDC credentials. Its composite action preserves legacy behavior for legacy declarations, but excludes stable GTM API aliases and their Routes when the new contract is explicit. It never invokes the API-alias reconciler: only the guarded Edge Gateway caller may change those two aliases.

Do not enable new GitOps API aliases until the Toolkit caller has migrated to this reviewed owner and old gateway deployments are suppressed. Keep the frozen legacy executor until real UAT owner/caller evidence permits its removal. Qualified Selfhost origins must have origin DNS and must not be bound back to a Worker, which would create a routing loop. PROD credentials/protection for the reusable owner must be reconciled separately; offline tests do not prove live Vault roles.

Provider APIs: [Worker Domains](https://developers.cloudflare.com/api/resources/workers/subresources/domains/), [Worker Routes](https://developers.cloudflare.com/api/resources/workers/subresources/routes/), and Cloudflare zone DNS records. Tests use a fake provider and never authenticate or change live DNS.
