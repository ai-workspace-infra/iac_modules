#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${VAULT_ADDR:?}" "${VAULT_TOKEN:?}" "${VAULT_ENV_PATH:?}" "${GCP_PROJECT_ID:?}"
case "$VAULT_ENV_PATH" in sit|uat|prod) ;; *) exit 2 ;; esac
[[ "$VAULT_ADDR" == https://vault.svc.plus ]] || exit 2
path="kv/data/$VAULT_ENV_PATH/platform/smtp/google"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
printf 'X-Vault-Token: %s\n' "$VAULT_TOKEN" > "$tmp/header"
status="$(curl --silent --show-error --max-time 20 -H "@$tmp/header" -o "$tmp/body" -w '%{http_code}' "$VAULT_ADDR/v1/$path" 2>/dev/null)"
if [[ "$status" == 404 ]]; then
  echo 'SMTP secret is not configured in the selected environment; no secret was changed.'
  exit 0
fi
[[ "$status" == 200 ]] || { echo '::error::SMTP Vault read failed.' >&2; exit 1; }
jq -e '.data.data | all(.username,.password; type == "string" and length > 0)' "$tmp/body" >/dev/null
for key in username password; do
  name="smtp-$key"
  jq -jr --arg key "$key" '.data.data[$key]' "$tmp/body" > "$tmp/desired"
  if ! gcloud secrets describe "$name" --project="$GCP_PROJECT_ID" --quiet >/dev/null 2>&1; then
    gcloud secrets create "$name" --replication-policy=automatic --project="$GCP_PROJECT_ID" --quiet >/dev/null 2>&1 || {
      echo '::error::Configured SMTP secret could not be created.' >&2; exit 1;
    }
  fi
  if ! gcloud secrets versions access latest --secret="$name" --project="$GCP_PROJECT_ID" --quiet > "$tmp/current" 2>/dev/null || ! cmp -s "$tmp/current" "$tmp/desired"; then
    gcloud secrets versions add "$name" --data-file="$tmp/desired" --project="$GCP_PROJECT_ID" --quiet >/dev/null 2>&1 || {
      echo '::error::Configured SMTP secret could not be updated.' >&2; exit 1;
    }
  fi
  gcloud secrets versions access latest --secret="$name" --project="$GCP_PROJECT_ID" --quiet > "$tmp/current" 2>/dev/null
  cmp -s "$tmp/current" "$tmp/desired" || { echo '::error::SMTP secret did not converge.' >&2; exit 1; }
done
echo 'SMTP Secret Manager values verified against the selected Vault record.'
