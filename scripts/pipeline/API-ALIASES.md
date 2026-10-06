# Accounts/Billing API DNS owner

The composite action `.github/actions/cloudflare-api-aliases` owns provider changes only. Its caller must pin an exact reviewed IaC commit, authenticate through its environment OIDC/Vault role, deploy Edge Gateway first, and provide the rendered fixed-SHA GitOps plan and exact gateway commit. Secrets remain in environment variables and never enter action inputs or checkpoints.

The explicit `api_alias_mode: worker-routes-cname` contract is required. Legacy declarations produce no DNS changes. Only the two canonical Accounts/Billing aliases and their qualified Serverless Worker domains are in scope. Brand, Console, Pages, unrelated records, and foreign Worker domains are preserved. All three Worker revisions, modes and four origins and all canonical boundary Routes must match the plan before mutations.

A private checkpoint is written before mutations. On provider failure this owner restores the two API aliases if their state has not changed concurrently; it refuses to overwrite another operator's changes. Re-running an already reconciled plan has no provider writes. A fresh checkpoint path is required per attempt. Do not publish checkpoints: provider record identifiers and private configuration remain operational data.

**Caller prerequisite:** any writer change must already have a trusted, fresh full-business equality and single-writer receipt. This DNS owner does not generate or validate database evidence and does not probe HTTP services. Its sanitized success receipt explicitly sets `business_verified=false`; Edge Gateway owns public HTTP verification after provider convergence.

Do not enable new GitOps API aliases while an active legacy publisher can rebind canonical API domains. Migrate that publisher to this IaC owner first. Qualified Selfhost origins must have origin DNS and must not be bound back to a Worker, which would create a routing loop.

Provider APIs: [Worker Domains](https://developers.cloudflare.com/api/resources/workers/subresources/domains/), [Worker Routes](https://developers.cloudflare.com/api/resources/workers/subresources/routes/), and Cloudflare zone DNS records. Tests use a fake provider and never authenticate or change live DNS.
