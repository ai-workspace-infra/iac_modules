# Cloudflare gateway DNS owner contract

`cloudflare-gateway-dns-upsert.py` is the IaC/provider owner for one declared
gateway `A` record. It is not a general DNS reconciler and it is not a Toolkit
workflow wrapper.

## Inputs

The caller must provide:

- `DNS_ENVIRONMENT`: exactly `uat` or `prod`.
- `CLOUDFLARE_ACCOUNT_ID`: one 32-character account id.
- `DNS_ZONE`: the exact active zone to query.
- `DNS_RECORD_NAME`: the record name, within `DNS_ZONE`.
- `DNS_TARGET_IP`: one public IPv4 address.
- `DNS_CHECKPOINT_PATH`: an absolute, non-symlink path on a private run volume.
- `CLOUDFLARE_DNS_API_TOKEN`: runtime-only provider credential.

`DNS_WAIT_FOR_RESOLVER` defaults to `true`; setting it to `false` is only
appropriate for a caller that performs an equivalent post-step convergence
check and records that evidence.

## Safety contract

1. Resolve exactly one active zone under the supplied account.
2. Refuse a non-`A` record conflict or more than one matching `A` record.
3. Write an atomic `0600` checkpoint before the provider mutation. The
   checkpoint is bound to environment, account, zone, name and target.
4. Preserve existing record attributes while setting the desired content,
   `ttl=60` and `proxied=false`.
5. Take an exclusive checkpoint lock and make retries idempotent.
6. If resolver convergence fails, restore only the exact record state recorded
   in the checkpoint; otherwise fail closed and require operator inspection.

The script never reads GitOps, renders CMDB, changes cloud instances, connects
to a host, restarts Caddy/Xray, or deletes unrelated records. It emits only
sanitized action/result values; the provider token must never enter logs or a
checkpoint.

## Caller and rollout boundary

The Toolkit owns dispatch, provider selection, approvals, environment policy,
target selection and release evidence. The first Toolkit caller change is a
separate dependent change and must pin the merged IaC commit. Until that
caller is deployed and its UAT acceptance is recorded, legacy DNS scripts stay
in place. Cleanup follows the repository migration order:

`owner implementation → Toolkit caller → verification → old-copy deletion`

Creation of CNAME/multi-record topologies, implicit cleanup, SIT-specific
reconciliation and CMDB publication are separate follow-up contracts.
