# Guarded Cloudflare A-record operation

The executor owns provider reads, a single existing A-record update, resolver
convergence and recovery from a runner-local checkpoint. Host restarts and
application health checks belong to Playbooks; the control workflow determines
their order and requests `DNS_ACTION=restore` if post-cutover acceptance fails.

Run `python3 scripts/pipeline/cloudflare-dns-record.py` with explicit
`DNS_ENVIRONMENT` (uat or prod), `DNS_ZONE`, `DNS_RECORD_NAME`,
`DNS_ACTION` (cutover, rollback, restore) and absolute `DNS_CHECKPOINT_PATH`.
Cutover requires `SOURCE_IP` and `TARGET_IP`; rollback requires `SOURCE_IP`
and optionally an expected `TARGET_IP`. The control workflow supplies the
environment approval and target declarations. `CLOUDFLARE_DNS_API_TOKEN` is
runtime-only and is never written to the checkpoint or outputs.

The checkpoint is created before the write, mode 0600. It preserves the original
address, TTL, proxy state, comment, tags and settings. Repeating a cutover with
the same checkpoint retains the original recovery point. Recovery verifies the
environment, record identity and complete expected record state before writing;
a concurrent external change causes recovery to fail rather than overwrite it.
Provider and resolver failures during cutover invoke recovery automatically.
An explicit rollback retains the source address on resolver failure and exits
nonzero. Keep the checkpoint until the ordered service acceptance has completed.

Outputs: `changed`, `record_id`, `address` through `GITHUB_OUTPUT`.
The executor does not create records, infer topology, or operate on hosts.

For production generation-only aliases, use
`cloudflare-generation-aliases.py --resources <fixed-GitOps-YAML> --cmdb
<IaC-generated-CMDB> --checkpoint <private-directory>` to render the four exact
`console`, `accounts`, `billing`, and `postgresql` `-selfhost-prod-vN.svc.plus`
records. The renderer verifies generation and service-domain agreement between
GitOps and CMDB and takes the public IP only from that CMDB entry. It then
preflights the exact four provider records as create/update/noop; duplicate A
records or another record type stop the run before writes. Add `--apply` only
after reviewing that exact preview. Root/public CNAMEs are outside this path.
