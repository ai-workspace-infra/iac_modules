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
| `ensure-gcp-vm-running.py`, `register-gcp-oslogin-key.sh` | GCP runtime reconcile and OS Login key |
| `verify-aws-boot-health.sh` | EC2 status-check gate |
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
