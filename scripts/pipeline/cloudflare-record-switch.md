# Reviewed existing DNS record switch

The control plane supplies a resolved plan on stdin with `environment` and a
bounded `records` list. Each row contains `zone`, `name`, `type` (`A` or `CNAME`),
`expected_content` and `content`. Resource addresses are runtime inputs, not
defaults in this provider executor. Provider credentials remain in the process
environment: `CLOUDFLARE_DNS_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.

Run `cloudflare-record-switch.py --checkpoint <absolute-private-path>` for a
read-only provider preview, then the same command with `--apply` after the
caller has authorized traffic handoff and established one writer. All records
are checked before the first mutation. Existing proxy flags, TTL and unrelated
MX/TXT records are retained. The executor cannot create or delete records.

The protected checkpoint records intent before API calls. Re-running the same
plan handles a lost API response by reading provider state before another write;
changed plans, record identities or unexpected concurrent content stop execution.
Provider verification is distinct from resolver/TLS/application verification.
There is no automatic DNS rollback or attempt to reopen the former DB writer.
Retain the original payloads for a separately reviewed recovery action; once new
business writes exist, restoring DNS alone is not database recovery.
