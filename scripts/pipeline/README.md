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
| `verify-aws-boot-health.sh` | EC2 status-check gate |

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
