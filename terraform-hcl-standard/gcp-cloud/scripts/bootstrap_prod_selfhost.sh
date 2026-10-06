#!/usr/bin/env bash
# One-time provider owner. Toolkit only selects sources/credentials and calls us.
set -euo pipefail
set +x
umask 077

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
REPO=$(cd -- "$ROOT/../.." && pwd)
LIB="$ROOT/scripts/lib"
STAGE=identity ACTION=plan GITOPS_DIR= GITOPS_REF= IAC_REF= APPROVED= ACCOUNT= WORKDIR=
stop() { echo "bootstrap stopped: $1" >&2; exit 1; }
cleanup() { if [[ -n "$WORKDIR" ]]; then rm -rf -- "$WORKDIR"; fi; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
usage() {
  cat <<'EOF'
Usage: bootstrap_prod_selfhost.sh --gitops-dir DIR --gitops-ref SHA --iac-ref SHA
       [--stage identity|external-ip] [--action plan|apply]
       [--approved-plan-sha256 SHA256] [--bootstrap-account EMAIL]
Prefer the Toolkit Shell entry: it prepares the fixed source checkouts.
--bootstrap-account explicitly selects a previously authorized local login for
this ONE-TIME repair only. There is no automatic account or credential fallback.
EOF
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --gitops-dir|--gitops-ref|--iac-ref|--stage|--action|--approved-plan-sha256|--bootstrap-account)
      [[ $# -ge 2 && -n "$2" ]] || stop 'missing option value'
      case "$1" in
        --gitops-dir) GITOPS_DIR=$2 ;; --gitops-ref) GITOPS_REF=$2 ;; --iac-ref) IAC_REF=$2 ;;
        --stage) STAGE=$2 ;; --action) ACTION=$2 ;; --approved-plan-sha256) APPROVED=$2 ;;
        --bootstrap-account) ACCOUNT=$2 ;;
      esac
      shift 2 ;;
    *) stop 'unsupported option' ;;
  esac
done
[[ "$STAGE" == identity || "$STAGE" == external-ip ]] || stop 'invalid stage'
[[ "$ACTION" == plan || "$ACTION" == apply ]] || stop 'invalid action'
[[ "$ACTION" != apply || "$APPROVED" =~ ^[0-9a-f]{64}$ ]] || stop 'apply requires reviewed plan digest'
for dependency in git jq ruby shasum terraform; do command -v "$dependency" >/dev/null || stop "missing dependency $dependency"; done
verify_checkout() {
  local directory=$1 ref=$2 repository=$3 head remote changes
  [[ "$ref" =~ ^[0-9a-f]{40}$ && -d "$directory" ]] || stop 'fixed source checkout required'
  head=$(git -C "$directory" rev-parse HEAD 2>/dev/null) || stop 'cannot verify source checkout'
  remote=$(git -C "$directory" remote get-url origin 2>/dev/null) || stop 'cannot verify source remote'
  changes=$(git -C "$directory" status --porcelain --untracked-files=all 2>/dev/null) || stop 'cannot inspect source changes'
  [[ "$head" == "$ref" && -z "$changes" ]] || stop 'source must be clean at fixed commit'
  case "$remote" in "https://github.com/$repository"|"https://github.com/$repository.git"|"git@github.com:$repository.git") ;; *) stop 'unexpected source repository' ;; esac
}
verify_checkout "$REPO" "$IAC_REF" ai-workspace-infra/iac_modules
verify_checkout "$GITOPS_DIR" "$GITOPS_REF" ai-workspace-infra/gitops
WORKDIR=$(mktemp -d "$ROOT/envs/.prod-selfhost-bootstrap-XXXXXXXX") || stop 'cannot prepare private workspace'
# Reuse the directory's existing Shell/Ruby YAML convention; no custom Python
# bootstrap/controller is involved. Only the shared IaC renderer remains Python.
ruby -ryaml -rjson -e '
  docs = ARGV.map { |p| YAML.safe_load(File.read(p), permitted_classes: [], aliases: false) }
  puts JSON.generate({oidc: docs[0], resource: docs[1]})
' "$GITOPS_DIR/resources/xworktech.com/prod/gcp/github-actions-oidc.yaml" \
  "$GITOPS_DIR/resources/svc.plus/prod/gcp/web-saas.yaml" >"$WORKDIR/declarations.json" 2>"$WORKDIR/private.log" || stop 'invalid YAML declaration'
guard() {
  # Only the module's fixed guard reasons may leave the private workspace.
  # jq parser diagnostics and provider/input values are never echoed.
  local reason
  if jq -L "$LIB" -e "$@" 2>"$WORKDIR/private.log"; then return; fi
  reason=$(sed -n 's/^jq: error (at .*): //p' "$WORKDIR/private.log")
  case "$reason" in
    'declaration kind mismatch'|'PROD declaration identity mismatch'|'WIF identity or subjects mismatch'|\
    'existing state key mismatch'|'resource namespace or policy allowance mismatch'|\
    'invalid or deferred Terraform plan'|'delete replace or unknown action rejected'|\
    'policy parent replacement rejected'|'policy name replacement rejected'|\
    'unexpected data dependency'|'write outside bootstrap targets'|'unknown target contract'|\
    'IAM API project mismatch'|'IAM grant mismatch'|'API enablement mismatch'|\
    'policy identity or local rule mismatch'|'broad conditional or incorrect policy'|\
    'existing policy requires separate review'|'duplicate or omitted bootstrap target'|\
    'existing state lineage serial required'|'existing protected state missing do not create second state')
      stop "$reason" ;;
    *) stop 'declaration plan or state guard rejected input' ;;
  esac
}
guard 'include "prod-bootstrap"; declarations' "$WORKDIR/declarations.json" >/dev/null

if [[ -n "$ACCOUNT" ]]; then
  [[ "$ACCOUNT" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]] || stop 'invalid bootstrap account'
  [[ -z "${GCP_BOOTSTRAP_ACCESS_TOKEN:-}" ]] || stop 'choose explicit account or explicit token'
  command -v gcloud >/dev/null || stop 'explicit local account requires gcloud'
  GCP_BOOTSTRAP_ACCESS_TOKEN=$(gcloud auth print-access-token --account="$ACCOUNT" 2>"$WORKDIR/private.log") || stop 'selected bootstrap account needs user login renewal'
fi
[[ -n "${GCP_BOOTSTRAP_ACCESS_TOKEN:-}" ]] || stop 'approved short lived bootstrap credential required'
for key in TF_STATE_ENDPOINT TF_STATE_BUCKET TF_STATE_ACCESS_KEY TF_STATE_SECRET_KEY TF_STATE_REGION; do
  [[ -n "${!key:-}" ]] || stop 'complete Vault state environment required'
done
[[ "$TF_STATE_ENDPOINT" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?/?$ ]] || stop 'invalid state endpoint'
[[ "$TF_STATE_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || stop 'invalid state bucket'
if [[ "$STAGE" == identity ]]; then DOC=oidc; else DOC=resource; fi
for pair in 'TF_STATE_ENDPOINT endpoint' 'TF_STATE_BUCKET bucket' 'TF_STATE_REGION region'; do
  read -r key field <<<"$pair"
  declared=$(jq -er --arg doc "$DOC" --arg field "$field" '.[$doc].spec.state[$field]' "$WORKDIR/declarations.json")
  [[ "${!key}" == "$declared" ]] || stop 'Vault backend differs from fixed GitOps contract'
done
STATE_KEY=$(jq -er --arg doc "$DOC" '.[$doc].spec.state.key' "$WORKDIR/declarations.json")
# Remove ambient provider/CLI/workspace overrides before any Terraform call.
while IFS= read -r variable; do
  case "$variable" in TF_VAR_*|TF_CLI_ARGS*|TF_LOG*|AWS_*|GOOGLE_*|GCLOUD_*|TF_WORKSPACE|TF_DATA_DIR|TF_CLI_CONFIG_FILE) unset "$variable" ;; esac
done < <(compgen -e)
export GOOGLE_OAUTH_ACCESS_TOKEN="$GCP_BOOTSTRAP_ACCESS_TOKEN"
export AWS_ACCESS_KEY_ID="$TF_STATE_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$TF_STATE_SECRET_KEY"
export AWS_EC2_METADATA_DISABLED=true TF_IN_AUTOMATION=1 TF_INPUT=0
unset GCP_BOOTSTRAP_ACCESS_TOKEN
tf() {
  terraform "-chdir=$WORKDIR" "$@" 2>"$WORKDIR/private.log" || stop "Terraform $1 failed raw provider output withheld"
}
hash_json() { jq -S -c . | tr -d '\n' | shasum -a 256 | cut -d ' ' -f 1; }
if [[ "$STAGE" == identity ]]; then
  cp "$ROOT/bootstrap/identity/main.tf" "$WORKDIR/main.tf"
  jq '.oidc.spec | {project_id,environment:"prod",github_owner:"ai-workspace-infra",
    github_repository:"platform-ops-toolkit",pool_id,provider_id,audience,
    deploy_service_account_id:.service_account_id,allowed_subjects:.subjects}' \
    "$WORKDIR/declarations.json" >"$WORKDIR/terraform.auto.tfvars.json"
else
  RENDER_PYTHON=${IAC_RENDER_PYTHON:-python3}
  "$RENDER_PYTHON" "$ROOT/scripts/generate.py" render \
    --resources "$GITOPS_DIR/resources/svc.plus/prod/gcp/web-saas.yaml" --workdir "$WORKDIR" \
    >"$WORKDIR/private.log" 2>&1 || stop 'shared IaC renderer unavailable check documented dependencies'
  jq --slurpfile docs "$WORKDIR/declarations.json" \
    '. + {deploy_service_account:"github-actions-prod@open-platform-prod.iam.gserviceaccount.com",
    workload_identity_provider:($docs[0].oidc.spec.audience|sub("^https://iam.googleapis.com/";""))}' \
    "$WORKDIR/terraform.auto.tfvars.json" >"$WORKDIR/vars.json"
  mv "$WORKDIR/vars.json" "$WORKDIR/terraform.auto.tfvars.json"
fi
tf init -input=false -reconfigure -no-color \
  "-backend-config=endpoint=$TF_STATE_ENDPOINT" "-backend-config=bucket=$TF_STATE_BUCKET" \
  "-backend-config=key=$STATE_KEY" "-backend-config=region=$TF_STATE_REGION" \
  -backend-config=skip_credentials_validation=true -backend-config=skip_metadata_api_check=true \
  -backend-config=skip_region_validation=true -backend-config=use_path_style=true \
  -backend-config=use_lockfile=true >"$WORKDIR/init.log"
tf fmt -check -no-color >"$WORKDIR/fmt.log"
tf validate -no-color >"$WORKDIR/validate.log"
tf state pull >"$WORKDIR/state.json"
snapshot() {
  local input=$1 output=$2 item address digest
  guard --arg stage "$STAGE" 'include "prod-bootstrap"; state_snapshot($stage)' "$input" >"$WORKDIR/snapshot.raw.json"
  jq '{lineage,serial,protected:{}}' "$WORKDIR/snapshot.raw.json" >"$output"
  while IFS= read -r item; do
    address=$(jq -r '.address' <<<"$item")
    digest=$(jq '.instances' <<<"$item" | hash_json)
    jq --arg address "$address" --arg digest "$digest" '.protected[$address]=$digest' "$output" >"$output.next"
    mv "$output.next" "$output"
  done < <(jq -c '.protected[]' "$WORKDIR/snapshot.raw.json")
}
snapshot "$WORKDIR/state.json" "$WORKDIR/before.json"
if [[ "$STAGE" == external-ip ]]; then
  command -v curl >/dev/null || stop 'policy read requires curl'
  POLICY_ID=projects/986070475391/policies/compute.vmExternalIpAccess
  # Pass header on stdin: never in process arguments or a credential file.
  [[ "$GOOGLE_OAUTH_ACCESS_TOKEN" != *$'\n'* && "$GOOGLE_OAUTH_ACCESS_TOKEN" != *'"'* && "$GOOGLE_OAUTH_ACCESS_TOKEN" != *'\'* ]] || stop 'invalid access token format'
  code=$(printf 'header = "Authorization: Bearer %s"\n' "$GOOGLE_OAUTH_ACCESS_TOKEN" |
    curl --config - --silent --show-error --max-time 30 --output "$WORKDIR/policy.json" \
      --write-out '%{http_code}' "https://orgpolicy.googleapis.com/v2/$POLICY_ID" 2>"$WORKDIR/private.log") || stop 'policy read failed no absence assumed'
  case "$code" in
    200)
      guard --arg id "$POLICY_ID" '.name == $id' "$WORKDIR/policy.json" >/dev/null
      if ! jq -e 'any(.resources[]; .mode == "managed" and .type == "google_org_policy_policy" and .name == "vm_external_ip_access" and (.module // "") == "")' "$WORKDIR/state.json" >/dev/null; then
        printf 'import {\n  to = google_org_policy_policy.vm_external_ip_access\n  id = "%s"\n}\n' "$POLICY_ID" >"$WORKDIR/adopt_policy.tf"
      fi ;;
    404) ;; *) stop 'policy read denied complete identity API repair first' ;;
  esac
fi
TARGET_ARGS=()
while IFS= read -r target; do TARGET_ARGS+=("-target=$target"); done < <(
  jq -n -r -L "$LIB" --arg stage "$STAGE" 'include "prod-bootstrap"; targets($stage)[]')
plan() {
  tf plan -input=false -no-color -lock-timeout=120s "-out=$WORKDIR/bootstrap.tfplan" "${TARGET_ARGS[@]}" >"$WORKDIR/plan.log"
  tf show -json "$WORKDIR/bootstrap.tfplan" >"$WORKDIR/plan.json"
  guard --arg stage "$STAGE" 'include "prod-bootstrap"; plan_targets($stage)' "$WORKDIR/plan.json" >"$WORKDIR/targets.raw.json"
}
plan
printf '[]\n' >"$WORKDIR/targets.json"
while IFS= read -r item; do
  digest=$(jq '._change' <<<"$item" | hash_json)
  jq --argjson item "$item" --arg digest "$digest" '. + [$item|del(._change) + {change_sha256:$digest}]' \
    "$WORKDIR/targets.json" >"$WORKDIR/targets.next.json"
  mv "$WORKDIR/targets.next.json" "$WORKDIR/targets.json"
done < <(jq -c '.[]' "$WORKDIR/targets.raw.json")
tf version -json >"$WORKDIR/version.json"
guard '.provider_selections["registry.terraform.io/hashicorp/google"]|type == "string"' "$WORKDIR/version.json" >/dev/null
jq -n --arg stage "$STAGE" --arg iac "$IAC_REF" --arg gitops "$GITOPS_REF" \
  --arg endpoint "$TF_STATE_ENDPOINT" --arg bucket "$TF_STATE_BUCKET" --arg key "$STATE_KEY" \
  --slurpfile before "$WORKDIR/before.json" --slurpfile targets "$WORKDIR/targets.json" --slurpfile version "$WORKDIR/version.json" \
  '{schema:1,owner:"iac_modules",scope:"prod-selfhost-bootstrap-only",project:"open-platform-prod",
    stage:$stage,iac_ref:$iac,gitops_ref:$gitops,backend:{endpoint:$endpoint,bucket:$bucket},
    state_key:$key,state_before:$before[0],targets:$targets[0],terraform_version:$version[0].terraform_version,
    google_provider_version:$version[0].provider_selections["registry.terraform.io/hashicorp/google"]}' >"$WORKDIR/receipt.json"
DIGEST=$(hash_json <"$WORKDIR/receipt.json")
if [[ "$ACTION" == apply ]]; then
  [[ "$APPROVED" == "$DIGEST" ]] || stop 'fresh plan differs from reviewed plan digest'
  tf apply -input=false -no-color -lock-timeout=120s "$WORKDIR/bootstrap.tfplan" >"$WORKDIR/apply.log"
  tf state pull >"$WORKDIR/state.json"
  snapshot "$WORKDIR/state.json" "$WORKDIR/after.json"
  guard -n --slurpfile before "$WORKDIR/before.json" --slurpfile after "$WORKDIR/after.json" \
    '$before[0].lineage == $after[0].lineage and $before[0].protected == $after[0].protected' >/dev/null
  plan
  guard 'all(.[]; .actions == ["no-op"])' "$WORKDIR/targets.raw.json" >/dev/null
  jq --slurpfile after "$WORKDIR/after.json" '.state_after=$after[0]' "$WORKDIR/receipt.json" >"$WORKDIR/receipt.next.json"
  mv "$WORKDIR/receipt.next.json" "$WORKDIR/receipt.json"
  RESULT=converged
else RESULT=review-required; fi
jq --arg action "$ACTION" --arg result "$RESULT" --arg digest "$DIGEST" \
  '. + {action:$action,result:$result,approved_plan_sha256:$digest,database_cutover_approved:false}' "$WORKDIR/receipt.json"
