#!/usr/bin/env bash
# Interactive CAS-protected helper to bootstrap the two one-time admin secrets in Vault KV v2:
#   kv/prod/platform/cloudflare (api_token, account_id)
#   kv/prod/platform/alicloud   (access_key_id, access_key_secret)
set -euo pipefail
set +x

usage() {
  printf '%s\n' \
    'Usage: bootstrap-admin-vault-kv.sh --provider cloudflare|alicloud [--rotate --expected-version N] [--preflight]' \
    'Requires: vault CLI, VAULT_ADDR, and an existing Vault login (VAULT_TOKEN or CLI token helper).' \
    'Prompts without echo and writes via stdin JSON using CAS=0 by default.'
}

provider='' rotate=false expected_version='' preflight=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider|--expected-version)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      case "$1" in
        --provider) provider="$2" ;;
        --expected-version) expected_version="$2" ;;
      esac
      shift 2
      ;;
    --rotate) rotate=true; shift ;;
    --preflight) preflight=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

case "$provider" in
  cloudflare) secret_path='prod/platform/cloudflare' ;;
  alicloud) secret_path='prod/platform/alicloud' ;;
  *) usage >&2; exit 2 ;;
esac

cas=0
if [[ "$rotate" == true ]]; then
  [[ "$expected_version" =~ ^[1-9][0-9]*$ ]] || { printf 'Rotation requires a positive --expected-version.\n' >&2; exit 2; }
  cas="$expected_version"
elif [[ -n "$expected_version" ]]; then
  printf '%s\n' '--expected-version requires --rotate.' >&2
  exit 2
fi

command -v vault >/dev/null || { printf 'vault CLI is required.\n' >&2; exit 1; }
command -v python3 >/dev/null || { printf 'python3 is required.\n' >&2; exit 1; }
[[ -n "${VAULT_ADDR:-}" ]] || { printf 'VAULT_ADDR is required.\n' >&2; exit 1; }

if [[ "$preflight" == true ]]; then
  vault token lookup >/dev/null 2>&1 || { printf 'FAIL: not logged in to %s.\n' "$VAULT_ADDR" >&2; exit 1; }
  if version="$(vault kv metadata get -mount=kv -field=current_version "$secret_path" 2>/dev/null)"; then
    printf 'OK: kv/%s exists at version %s; pass --rotate --expected-version %s to replace.\n' "$secret_path" "$version" "$version"
  else
    printf 'OK: kv/%s has no record yet (first write uses CAS=0).\n' "$secret_path"
  fi
  exit 0
fi

[[ -t 0 ]] || { printf 'Run interactively to enter credentials without echo.\n' >&2; exit 1; }
printf 'Vault target: %s\nKV record: kv/%s\nCAS version: %s\n' "$VAULT_ADDR" "$secret_path" "$cas"
read -r -p "Type '$provider' to confirm: " confirm
[[ "$confirm" == "$provider" ]] || { printf 'Cancelled.\n' >&2; exit 1; }

field_a='' field_b=''
trap 'unset field_a field_b' EXIT

if [[ "$provider" == cloudflare ]]; then
  read -r -p 'Enter Cloudflare account_id (non-secret): ' field_b
  read -r -s -p 'Enter Cloudflare api_token: ' field_a
  printf '\n'
  [[ -n "$field_a" && -n "$field_b" ]] || { printf 'Both api_token and account_id are required.\n' >&2; exit 1; }
  payload="$(python3 -c 'import json, os; print(json.dumps({"api_token": os.environ["A"], "account_id": os.environ["B"]}))' A="$field_a" B="$field_b")"
else
  read -r -p 'Enter Aliyun access_key_id: ' field_a
  read -r -s -p 'Enter Aliyun access_key_secret: ' field_b
  printf '\n'
  [[ -n "$field_a" && -n "$field_b" ]] || { printf 'Both access_key_id and access_key_secret are required.\n' >&2; exit 1; }
  payload="$(python3 -c 'import json, os; print(json.dumps({"access_key_id": os.environ["A"], "access_key_secret": os.environ["B"]}))' A="$field_a" B="$field_b")"
fi

if ! printf '%s' "$payload" | vault kv put -mount=kv -cas="$cas" "$secret_path" - >/dev/null 2>&1; then
  printf 'Write failed. Verify Vault login, KV v2 mount, policy, and CAS version.\n' >&2
  exit 1
fi
printf 'Successfully updated kv/%s (CAS=%s).\n' "$secret_path" "$cas"
