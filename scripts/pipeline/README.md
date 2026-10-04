# scripts/pipeline

Terraform / provision-phase steps that the `platform-ops-toolkit` workflows run. The
toolkit checks this repository out (as `infra/iac_modules/` or `iac_modules/`) and calls
these scripts from the Terraform working directory, so every relative path in them
(`cmdb.json`, `config/resources/...`, `gitops/...`) resolves against the step's
`working-directory`, not against this folder.

| Script | Step |
|--------|------|
| `install-render-deps.sh` | Python deps for `scripts/generate.py` |
| `map-instance-plan.sh` | `2C2G`-style plan → provider instance type |
| `resolve-golden-image-snapshots.sh` | golden image snapshot lookup |
| `terraform-init.sh` | `terraform init` with the S3 state backend |
| `adopt_uat_open_platform_vm.py` | import an existing UAT VM into state |
| `reconcile-terraform-state.sh` | drop orphaned / drifted state entries before apply |
| `terraform-apply-destroy.sh` | plan / apply / destroy with the UAT no-delete and Vultr no-downgrade guards |
| `assert-destroy-scope.sh` | refuses a destroy whose scope is empty or wrong; called by the script above and by the Akamai pipeline |
| `adopt-resize-replacement.sh`, `resize-instance-apply-terraform.sh` | guarded resize flow |
| `vultr-instance-snapshot.sh` | create or resume a Vultr instance snapshot and wait for completion |
| `ensure-gcp-vm-running.py`, `register-gcp-oslogin-key.sh` | GCP runtime reconcile and OS Login key |
| `gcp-temporary-ssh-access.sh open\|close` | short-lived runner SSH access to one OS Login VM: RUNNING reconcile, target facts, one-run OS Login key with TTL, runner-/32 tag-scoped tcp:22 rule; revocation with rollback |
| `verify-aws-boot-health.sh` | EC2 status-check gate |
| `cloudflare-dns-record.py` | single A-record cutover/rollback with an environment-bound checkpoint and guarded recovery; see [contract](cloudflare-dns-record.md) |
| `dns-reconcile.py plan\|apply\|restore` | UAT gateway single-A upsert with explicit account/zone/record identity, checkpoint recovery and exact resolver verification; see [contract](dns-reconcile.md) |
| `artifact-registry-wait.sh` | bounded wait for an exact image tag or digest in Artifact Registry |
| `artifact-registry-promote.sh` | idempotent, same-digest image promotion into a target repository |

The Artifact Registry executors use the caller's Google Cloud identity and
accept the full repository URI, image tag and bounded wait budget as inputs.
Promotion also requires a single service entry in a caller-validated UAT
manifest. An occupied release tag with another digest fails without writes;
success writes `digest` to `GITHUB_OUTPUT` when available. The control workflow
owns release provenance checks and decides when to invoke these operations.

`gcp-temporary-ssh-access.sh` takes `GCP_PROJECT_ID`, `GCP_ZONE`,
`GCP_INSTANCE`, `GCP_NETWORK`, a per-run `ACCESS_RULE_NAME` and a private,
not-yet-existing `ACCESS_DIR`; optional `OSLOGIN_KEY_TTL` (default `20m`, at
most `120m`), `TARGET_TAGS` (default: the VM's network tags), `SOURCE_IP`
(default: the runner's public egress address) and `ENSURE_RUNNING` (default
`true`). `open` writes `ACCESS_DIR/access.json` (`target_ip`, `target_tags`,
`ssh_user`, `private_key`, `known_hosts`, `firewall_rule`, `source_range`,
`oslogin_key_ttl`) and the same facts to `GITHUB_OUTPUT`; the OS Login user is
masked in Actions. It refuses an existing rule or directory, and a failed open
removes what it created. `close` takes the same rule name and directory, is
idempotent, keeps revoking after a failed step and exits non-zero unless the
rule is confirmed absent and the key revoked. The caller runs `close` on every
exit path and owns target selection, credentials and what runs over SSH.

AWS boot readiness requires both EC2 checks to be `ok`, then an SSH banner.
`AWS_BOOT_HEALTH_TIMEOUT_SECONDS` defaults to 600 seconds per instance;
`AWS_SSH_BANNER_TIMEOUT_SECONDS` defaults to 180 seconds. Both budgets and
their polling intervals can be overridden by the caller. A timeout fails the
pipeline and captures console diagnostics; it never bypasses readiness.

`vultr-instance-snapshot.sh` requires `VULTR_API_KEY` and `INSTANCE_ID` from the
caller. It optionally accepts `VULTR_SNAPSHOT_ID` to resume waiting without
creating another backup, plus `VULTR_SNAPSHOT_WAIT_ATTEMPTS` and
`VULTR_SNAPSHOT_WAIT_INTERVAL_SECONDS`. On success it writes `snapshot_id` to
`GITHUB_OUTPUT` when present, otherwise stdout. Approval and exact instance
selection stay with the caller; a failed snapshot stops replacement before
Terraform runs. The script does not delete snapshots.
| `reconcile-backup-schedules.sh` | provider backup schedule reconcile |
| `action-runner-iac.sh` | `render` / `terraform-init` / `terraform-action` / `inventory` / `build-matrix` for the runner VM |
| `multi-cloud-load-aws-config.sh`, `multi-cloud-terraform-cli-args.sh <accounts\|resources>` | multi-cloud matrix backend config |
| `lib/require-env.sh` | `require_env` guard, sourced by the scripts above |

`lib/require-env.sh` is a byte-identical copy of the one in `playbooks` and in
`platform-ops-toolkit/.github/scripts/lib/`; each repo keeps its own so a pinned ref
never depends on another repo's layout.

## Tests

`scripts/pipeline/tests/` runs in `.github/workflows/pipeline-scripts.yml`:

```bash
for t in scripts/pipeline/tests/*_test.sh; do bash "$t"; done
python3 -m unittest discover -s scripts/pipeline/tests -p '*test*.py'
```

## Repository boundary and change order

This directory owns Terraform and provision-phase behavior only. The orchestrator and
GitOps readers stay in
[`platform-ops-toolkit/.github/scripts/`](https://github.com/ai-workspace-infra/platform-ops-toolkit/tree/main/.github/scripts),
Ansible-phase behavior stays in
[`playbooks/scripts/pipeline/`](https://github.com/ai-workspace-infra/playbooks/tree/main/scripts/pipeline),
and desired state stays as YAML/Markdown data in
[`gitops`](https://github.com/ai-workspace-infra/gitops).

For a change crossing repositories, land the IaC and playbooks additions first, then
update toolkit call sites in a dependent PR. The dependent toolkit PR must name the
upstream PRs and the required merge order. Do not add workflow-prefixed wrappers here;
use a short-hyphen script name, add a test under `scripts/pipeline/tests/`, and keep
direct entry points executable (`100755`).

`lib/require-env.sh` is intentionally byte-identical to the copies in playbooks and
toolkit. Keep the copy local to this repository; do not source a helper through a sibling
checkout. Release and branch rules are maintained in
[`skills/release-branch-policy/SKILL.md`](../../skills/release-branch-policy/SKILL.md).
