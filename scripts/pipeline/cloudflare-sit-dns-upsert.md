# SIT Cloudflare DNS upsert

`cloudflare-sit-dns-upsert.py` is a local IaC/provider executor for one declared
SIT A record in the `svc.plus` zone. It accepts DNS labels containing
underscores while the shared UAT/PROD gateway executor keeps its hostname
validator and environment scope unchanged.

Required runtime inputs are `DNS_ENVIRONMENT=sit`, `DNS_ZONE=svc.plus`,
`DNS_RECORD_NAME`, `DNS_TARGET_IP`, `CLOUDFLARE_ACCOUNT_ID`,
`CLOUDFLARE_DNS_API_TOKEN`, and a private absolute `DNS_CHECKPOINT_PATH`.
For an existing A record, also provide `DNS_EXPECTED_CURRENT_IP`; the executor
refuses to update any unexpected current value or non-A/duplicate record.
New records are created only when no record of any type occupies that name.

The executor uses the common checkpoint and resolver verification path. It
does not perform host or application health checks. Underscore labels may not
work as browser hostnames or pass TLS hostname validation; verify client and
certificate compatibility before publishing such a URL.
