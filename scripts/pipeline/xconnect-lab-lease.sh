#!/usr/bin/env bash
set -euo pipefail
umask 077
mkdir -p "${LAB_DIR:?}"
state_api() {
  AWS_ACCESS_KEY_ID="$TF_STATE_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$TF_STATE_SECRET_KEY" \
    AWS_SESSION_TOKEN='' AWS_REGION="$TF_STATE_REGION" \
    aws --endpoint-url "$TF_STATE_ENDPOINT" s3api "$@" > "$LAB_DIR/state-api.log" 2>&1
}
run="$(<"$LAB_DIR/run-id")"
[[ "$run" =~ ^xcl-[0-9]+-[0-9]+$ ]] || exit 2
prefix=runs/uat/svc.plus/aws-cloud/primary/xconnect-lab
case "${1:?}" in
  create)
    for ref in IAC_REF GITOPS_REF PLAYBOOKS_REF; do
      [[ "${!ref:-}" =~ ^[0-9a-f]{40}$ ]] || { echo "::error::$ref must be an immutable commit SHA" >&2; exit 2; }
    done
    for tag in CLI_RELEASE_TAG GATEWAY_RELEASE_TAG XRAY_RELEASE_TAG; do
      [[ "${!tag:-}" =~ ^v[0-9][0-9A-Za-z._-]*$ ]] || { echo "::error::$tag must be an immutable release tag" >&2; exit 2; }
    done
    jq -n --arg run "$run" --arg iac "$IAC_REF" --arg gitops "$GITOPS_REF" --arg playbooks "$PLAYBOOKS_REF" \
      --arg cli "$CLI_RELEASE_TAG" --arg gateway "$GATEWAY_RELEASE_TAG" --arg xray "$XRAY_RELEASE_TAG" \
      --arg provider "${GATEWAY_PROVIDER:-external}" --arg external_gateway_id "${EXTERNAL_GATEWAY_ID:-}" \
      --arg external_network_id "${EXTERNAL_NETWORK_ID:-}" --arg external_server_name "${EXTERNAL_GATEWAY_SERVER_NAME:-}" \
      --arg gateway_wireguard_address "${GATEWAY_WIREGUARD_ADDRESS:-}" \
      --arg expires "$(jq -r .expires_at "$LAB_DIR/variables.json")" \
      '{run:$run,expires_at:$expires,inputs:{mode:"cleanup",cleanup_run:$run,iac_ref:$iac,gitops_ref:$gitops,playbooks_ref:$playbooks,cli_release_tag:$cli,gateway_release_tag:$gateway,xray_release_tag:$xray,gateway_provider:$provider,external_gateway_id:$external_gateway_id,external_network_id:$external_network_id,external_gateway_server_name:$external_server_name,gateway_wireguard_address:$gateway_wireguard_address}}' > "$LAB_DIR/lease.json"
    state_api put-object --bucket "$TF_STATE_BUCKET" --key "$prefix/$run.json" --body "$LAB_DIR/lease.json"
    ;;
  delete)
    state_api delete-object --bucket "$TF_STATE_BUCKET" --key "$prefix/$run.json"
    ;;
  *) exit 2 ;;
esac
