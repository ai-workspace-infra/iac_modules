# Dev onwalk create-only DNS owner

Owner: IaC Modules. This narrow provider entrypoint creates only the six approved
flat `onwalk.net` A records for the single current Dev K3s target. It is not a
new general DNS platform. The old gateway upsert CLI remains UAT/PROD-only and
is not called with a fabricated environment. This entrypoint reuses its
Cloudflare client, IPv4 guard and atomic checkpoint writer, plus the existing
unified provider JSON GET helper. It never calls the old update/restore/delete
executor.

## Trusted handoff

The existing control plane authenticates its IaC artifact/run and reviewed
GitOps source, then supplies two local nonsecret files:

- `--plan`: exact fields `schema: dev-onwalk-dns/v1`, `environment: dev`,
  `feature_id: xconnect-referral`, `zone: onwalk.net`, full 40-hex `gitops_sha`,
  exact `cmdb_sha256`, stable per-operation `operation_id`, `hostnames`, and
  `expected_target` containing only `target_id`, `instance_id`, `name`, `label`,
  `region`, `account`.
- `--cmdb`: the unchanged hash-bound single-target IaC inventory:
  `dev-akamai-dev-k3s-v5 → dev-k3s-v5 → host facts`. Name/label/cluster must be
  `dev-k3s-v5`, provider Akamai, groups Dev (not UAT/PROD). Address is parsed
  from this artifact, never supplied as a DNS CLI override or historical IP.

The six `hostnames` must exactly equal:

- xconnect-referral-sit.onwalk.net
- accounts-xconnect-referral-sit.onwalk.net
- billing-xconnect-referral-sit.onwalk.net
- web-saas-uat.onwalk.net
- accounts-web-saas-uat.onwalk.net
- billing-web-saas-uat.onwalk.net

Provider owner does not fetch GitHub, Vault, SSH or DB state. A syntactically
valid GitOps SHA/file hash is not a substitute for control-plane authentication.
It independently checks the Linode account profile, exact ID/current
label/region/running/IP, and a filtered unique-label listing before any DNS
mutation and again before each create. The label cannot select production.
Cloudflare must return the exact active onwalk zone under `CF_ACCOUNT`.

## Runtime use and scope

Use an existing IaC Python runtime with the repository's existing PyYAML
parser dependency. Parent supplies only runtime environment credentials
`CF_ACCOUNT`, `CF_API_TOKEN`, `LINODE_TOKEN`; no secret lookup, credential-file
copy, new Vault role or dispatch token input is added here. Never print those
values. Input files, checkpoints and receipts contain no token values.

```sh
python3 scripts/pipeline/dev-onwalk-dns-create.py \
  --plan /private/run/dev-dns-plan.json \
  --cmdb /private/run/inventory.json \
  --checkpoint /private/run/dev-onwalk-checkpoint.json
# After the task's exact review/authorization, parent adds --apply.
```

Default mode performs provider reads and returns `PLANNED`, not creation.
The checkpoint parent must be private; checkpoint/lock files are 0600 and
writes are atomic/exclusively locked. No IP, instance ID or token is embedded
in this source or a GitOps declaration by the executor.

## Create-only and failure behavior

All six exact record names are listed before the first create. Any preexisting
A/AAAA/CNAME/other record refuses the whole initial batch, even if its address
already matches. No existing record is adopted. Creates are fixed A, TTL60,
unproxied, with a comment binding this exact operation plan. Each confirmed
created record ID is checkpointed immediately and read back. Retry accepts
only the same checkpoint/plan/zone/account/current target, exact recorded ID,
owner comment and target/attributes. Missing, replaced or changed records block;
there is no PUT, DELETE, implicit cleanup, retarget or fallback to another zone.

A second read before each create narrows concurrent-writer races. Cloudflare
has no atomic absence-and-create transaction across six names; post-create
readback detects conflicts. Partial errors preserve all confirmed IDs with
`BLOCKED_PARTIAL`; rerun the same plan/checkpoint after inspection to continue.
A create whose response was lost cannot be adopted without its recorded ID:
stop for explicit operator review instead of silently deleting or overwriting.
Provider errors are sanitized; no API bodies, headers or environment dumps are
printed. Success `CREATED_API_VERIFIED` means API readback only;
`dns_resolution` and `tls` remain `NOT_RUN`, not public propagation/ACME/service
acceptance. Those are separate parent/owner verification steps.

No actual DNS mutation was executed while implementing this change. There is
currently no wired Dev formal workflow caller for this new bounded entrypoint;
parent may invoke the reviewed CLI under existing authorization, recording a
manual owner receipt, not inventing a GitHub dispatch/run. A later fixed-SHA
control-plane caller must pass the same trusted plan/CMDB contract.
