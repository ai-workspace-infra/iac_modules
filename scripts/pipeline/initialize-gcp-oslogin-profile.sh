#!/usr/bin/env bash
# First profile creation only. No SSH session, firewall or host operation.
# The unused public key expires in one minute and is revoked before success.
set -euo pipefail
umask 077

project="${1:-}"
principal="${2:-}"
[[ "$project" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || {
  echo 'OS Login initialization requires a verified project.' >&2; exit 1;
}
[[ "$principal" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]@${project}\.iam\.gserviceaccount\.com$ ]] || {
  echo 'OS Login initialization requires the exact project service account.' >&2; exit 1;
}
: "${GOOGLE_GHA_CREDS_PATH:?GitHub WIF credential is required}"
expected="https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${principal}:generateAccessToken"
jq -e --arg expected "$expected" \
  '.type == "external_account" and .service_account_impersonation_url == $expected' \
  "$GOOGLE_GHA_CREDS_PATH" >/dev/null 2>&1 || {
  echo 'OS Login initialization refuses a different WIF principal.' >&2; exit 1;
}
command -v timeout >/dev/null || { echo 'Bounded OS Login command runner is required.' >&2; exit 1; }
task_dir="$(mktemp -d)"
registered=false
cleanup() {
  local result=$?
  trap - EXIT
  if [[ "$registered" == true ]]; then
    if ! timeout 30s gcloud --quiet compute os-login ssh-keys remove \
      --project="$project" --account="$principal" --key-file="$task_dir/key.pub" >/dev/null 2>&1; then
      echo 'Temporary OS Login key revocation failed; key expires after one minute. Inventory refused.' >&2
      result=1
    fi
  fi
  rm -rf "$task_dir"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
ssh-keygen -q -t ed25519 -N '' -C 'ci-oslogin-profile-initialization' -f "$task_dir/key" >/dev/null 2>&1
# This key is never used to connect. Delete private material before registration.
rm -f "$task_dir/key"
# Attempt cleanup even if the API accepts the key but the client times out.
registered=true
if ! timeout 30s gcloud --quiet compute os-login ssh-keys add \
  --project="$project" --account="$principal" --key-file="$task_dir/key.pub" --ttl=1m >/dev/null 2>&1; then
  echo 'Exact runtime OS Login profile initialization failed.' >&2
  exit 1
fi
