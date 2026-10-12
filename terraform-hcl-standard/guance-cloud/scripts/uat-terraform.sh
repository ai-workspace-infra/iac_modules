#!/usr/bin/env bash
# Controlled UAT plan/apply for Guance. The plan is written to a private temp directory,
# inspected by plan_guard.py (no delete/replace, no unreviewed import diff) and removed on
# exit; plan files and plan JSON may contain sensitive values and are never uploaded.
#
# Required environment (injected from Vault by CI, never written to disk):
#   GUANCE_ACCESS_TOKEN                      management API key (provider-native variable)
#   TF_STATE_ENDPOINT/BUCKET/ACCESS_KEY/SECRET_KEY/REGION   state backend
#   TF_VAR_guance_notify_<id>_opt_set        one JSON string per declared notify object
set -euo pipefail
set +x
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
usage() {
  printf '%s\n' 'Usage: uat-terraform.sh plan|apply --resources MANIFEST --workdir DIR [--expect-no-changes] [--allow-import-updates] [--allow-delete ADDRESS] [--existing FILE]'
}
mode="${1:-}"; shift || true
[[ "$mode" == plan || "$mode" == apply ]] || { usage >&2; exit 2; }
resources='' workdir='' existing='' guard_args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --resources) resources="${2:?}"; shift 2 ;;
    --workdir) workdir="${2:?}"; shift 2 ;;
    --existing) existing="${2:?}"; shift 2 ;;
    --expect-no-changes|--allow-import-updates) guard_args+=("$1"); shift ;;
    --allow-delete) guard_args+=("$1" "${2:?}"); shift 2 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ -n "$resources" && -n "$workdir" ]] || { usage >&2; exit 2; }
[[ -n "${GUANCE_ACCESS_TOKEN:-}" ]] || { printf 'GUANCE_ACCESS_TOKEN is required (Vault management record).\n' >&2; exit 1; }
tf="${TERRAFORM:-terraform}"
# shellcheck source-path=SCRIPTDIR source=tf-env.sh
source "$here/tf-env.sh" || exit 1
scratch="$(umask 077 && mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

python3 "$here/generate.py" render --resources "$resources" --workdir "$workdir"
if [[ -n "$existing" ]]; then
  python3 "$here/generate.py" import --resources "$resources" --workdir "$workdir" --existing "$existing"
fi
bash "$here/tf-init.sh" --workdir "$workdir" --resources "$resources" >/dev/null
"$tf" -chdir="$workdir" validate -no-color >/dev/null
"$tf" -chdir="$workdir" plan -input=false -lock-timeout=120s -no-color -out="$scratch/plan.tfplan" >"$scratch/plan.txt"
"$tf" -chdir="$workdir" show -json "$scratch/plan.tfplan" >"$scratch/plan.json"

# Human-readable plan: Terraform redacts sensitive values; suppress it entirely if anything credential-shaped remains.
if python3 "$here/secret_scan.py" "$scratch/plan.txt" >/dev/null 2>&1; then
  grep -E '^(Plan:|No changes|  # |Terraform will perform)' "$scratch/plan.txt" || true
else
  printf 'Plan text withheld: credential-shaped content detected.\n' >&2
fi
python3 "$here/plan_guard.py" --plan "$scratch/plan.json" ${guard_args[@]+"${guard_args[@]}"}

if [[ "$mode" == apply ]]; then
  "$tf" -chdir="$workdir" apply -input=false -lock-timeout=120s -no-color "$scratch/plan.tfplan" >/dev/null
  "$tf" -chdir="$workdir" output -json >"$scratch/outputs.json"
  python3 "$here/generate.py" inventory --resources "$resources" --workdir "$workdir" --outputs "$scratch/outputs.json"
  printf 'Applied. CMDB written to %s/cmdb.json\n' "$workdir"
fi
