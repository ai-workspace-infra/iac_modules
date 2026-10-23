#!/usr/bin/env bash
set -euo pipefail
umask 077
usage() {
  echo "Usage: provision.sh --provider aws-cloud|gcp-cloud|akamai-cloud --env ENV --deployment-id ID --resources FILE --workdir DIR --phase plan|apply|verify [--plan-file FILE] [--allow-prod-replacement]"
}
die() { echo "error: $*" >&2; exit 2; }
need() { command -v "$1" >/dev/null || die "missing command: $1"; }
ENVIRONMENT= DEPLOYMENT_ID= PROVIDER= RESOURCES= WORKDIR= PHASE= PLAN_FILE= ALLOW_PROD_REPLACEMENT=0
while (($#)); do
  case "$1" in
    --provider) PROVIDER=$2; shift 2;; --env) ENVIRONMENT=$2; shift 2;; --deployment-id) DEPLOYMENT_ID=$2; shift 2;;
    --resources) RESOURCES=$2; shift 2;; --workdir) WORKDIR=$2; shift 2;; --phase) PHASE=$2; shift 2;;
    --plan-file) PLAN_FILE=$2; shift 2;; --allow-prod-replacement) ALLOW_PROD_REPLACEMENT=1; shift;;
    -h|--help) usage; exit 0;; *) usage >&2; die "unknown argument: $1";;
  esac
done
[[ -n "$PROVIDER" && -n "$ENVIRONMENT" && -n "$DEPLOYMENT_ID" && -n "$RESOURCES" && -n "$WORKDIR" && -n "$PHASE" ]] || { usage >&2; exit 2; }
[[ "$ENVIRONMENT" =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]] || die "invalid environment"
[[ "$DEPLOYMENT_ID" =~ ^[a-z0-9][a-z0-9-]{1,63}$ ]] || die "invalid deployment id"
[[ -f "$RESOURCES" ]] || die "resources file not found"
case "$PROVIDER" in aws-cloud|gcp-cloud|akamai-cloud) ;; *) die "unsupported provider: $PROVIDER";; esac
case "$PHASE" in plan|apply|verify) ;; *) die "phase must be plan, apply, or verify";; esac
if [[ "$ALLOW_PROD_REPLACEMENT" == 1 && ( "$PROVIDER" != akamai-cloud || "$ENVIRONMENT" != prod ) ]]; then
  die "--allow-prod-replacement requires --provider akamai-cloud --env prod"
fi
need python3; need terraform
IAC_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
GENERATOR="$IAC_ROOT/terraform-hcl-standard/$PROVIDER/scripts/generate.py"
[[ -f "$GENERATOR" ]] || die "generator not found: $GENERATOR"
mkdir -p "$WORKDIR"
RENDER_ARGS=()
if [[ "$ALLOW_PROD_REPLACEMENT" == 1 ]]; then
  RENDER_ARGS+=(--allow-prod-replacement)
fi
python3 "$GENERATOR" render --resources "$RESOURCES" --workdir "$WORKDIR" "${RENDER_ARGS[@]}"
terraform -chdir="$WORKDIR" init -input=false
if [[ -z "$PLAN_FILE" ]]; then PLAN_FILE="$WORKDIR/$DEPLOYMENT_ID.tfplan"; fi
if [[ "$PHASE" == apply ]]; then
  [[ -f "$PLAN_FILE" ]] || die "apply requires a reviewed plan file: $PLAN_FILE"
  terraform -chdir="$WORKDIR" apply -input=false "$PLAN_FILE"
  python3 "$GENERATOR" inventory --resources "$RESOURCES" --workdir "$WORKDIR"
elif [[ "$PHASE" == plan ]]; then
  terraform -chdir="$WORKDIR" plan -input=false -out="$PLAN_FILE"
  echo "review plan before apply: $PLAN_FILE"
else
  terraform -chdir="$WORKDIR" plan -input=false -detailed-exitcode
fi
receipt_dir=$(dirname "$WORKDIR")/receipts
mkdir -p "$receipt_dir"
printf '{"environment":"%s","deployment_id":"%s","provider":"%s","phase":"%s","resources":"%s","workdir":"%s","allow_prod_replacement":%s}\n' "$ENVIRONMENT" "$DEPLOYMENT_ID" "$PROVIDER" "$PHASE" "$RESOURCES" "$WORKDIR" "$([[ "$ALLOW_PROD_REPLACEMENT" == 1 ]] && echo true || echo false)" >"$receipt_dir/$DEPLOYMENT_ID-provision-$PHASE.json"
chmod 0600 "$receipt_dir/$DEPLOYMENT_ID-provision-$PHASE.json"

