# shellcheck shell=bash
# Source me. Validates the unified TF_STATE_* contract and maps it to standard AWS S3 backend env vars.
for _name in TF_STATE_ENDPOINT TF_STATE_BUCKET TF_STATE_ACCESS_KEY TF_STATE_SECRET_KEY TF_STATE_REGION; do
  [[ -n "${!_name:-}" ]] || { printf 'Missing %s (inject from kv/CICD/prod/iac_state).\n' "$_name" >&2; return 1; }
done
[[ "$TF_STATE_ENDPOINT" =~ ^https?://[A-Za-z0-9.:-]+/?$ ]] || { printf 'Invalid TF_STATE_ENDPOINT.\n' >&2; return 1; }
[[ "$TF_STATE_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || { printf 'Invalid TF_STATE_BUCKET.\n' >&2; return 1; }
export AWS_ACCESS_KEY_ID="$TF_STATE_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$TF_STATE_SECRET_KEY"
export AWS_REGION="$TF_STATE_REGION" AWS_ENDPOINT_URL_S3="$TF_STATE_ENDPOINT"
unset AWS_SESSION_TOKEN AWS_PROFILE
