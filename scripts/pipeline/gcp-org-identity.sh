#!/usr/bin/env bash
# IaC owner entrypoint for .github/actions/gcp-org-identity. Inputs via env only:
#   OP (resolve-oidc-config|external-ip-policy), GCP_ENVIRONMENT, DECLARATION,
#   MODE (render|apply), OWNER_SHA. Writes a receipt and prints its path.
# Every input/declaration check runs before any gcloud call.
set -euo pipefail
die() { echo "::error::$*" >&2; exit 2; }
: "${OP:?}" "${GCP_ENVIRONMENT:?}" "${DECLARATION:?}" "${MODE:=render}"
case "$GCP_ENVIRONMENT" in uat|prod|shared) ;; *) die 'invalid environment' ;; esac
case "$MODE" in render|apply) ;; *) die 'mode must be render or apply' ;; esac
[[ -f "$DECLARATION" ]] || die "declaration not found: $DECLARATION"
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/maintenance/gcp"
case "$OP" in
  resolve-oidc-config)
    [[ "$MODE" == render ]] || die 'resolve-oidc-config is read-only'
    # resolver enforces metadata.environment == GCP_ENVIRONMENT
    GCP_OIDC_CONFIG="$DECLARATION" GCP_ENVIRONMENT="$GCP_ENVIRONMENT" bash "$dir/resolve_github_oidc_config.sh" >/dev/null ;;
  external-ip-policy)
    # The org policy only exists for the shared project; uat/prod would act on
    # shared while labelling the receipt with another environment.
    [[ "$GCP_ENVIRONMENT" == shared ]] || die "external-ip-policy is shared-only, got environment=$GCP_ENVIRONMENT"
    bash "$dir/seed_shared_external_ip_policy.sh" --manifest "$DECLARATION" --environment "$GCP_ENVIRONMENT" "--$MODE" >&2 ;;
  *) die 'Unregistered GCP identity operation' ;;
esac
receipt="$(mktemp "${RUNNER_TEMP:-/tmp}/gcp-identity-receipt.XXXXXX.json")"
jq -n --arg op "$OP" --arg env "$GCP_ENVIRONMENT" --arg mode "$MODE" --arg owner "${OWNER_SHA:-}" \
  --arg run "${GITHUB_RUN_ID:-}" --arg attempt "${GITHUB_RUN_ATTEMPT:-}" \
  '{schema:1,accepted:true,scope:"gcp-org-identity",owner_repository:"ai-workspace-infra/iac_modules",
    owner_commit:$owner,run_id:$run,run_attempt:$attempt,environment:$env,declaration_environment:$env,
    operation:$op,mode:$mode}' > "$receipt"
echo "$receipt"
