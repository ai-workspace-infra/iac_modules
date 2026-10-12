#!/usr/bin/env bash
set -euo pipefail
set +x

usage() {
  printf '%s\n' 'Usage: bootstrap-vault-kv.sh --env uat|prod --workspace ALIAS --purpose management|query|ingest [--rotate --expected-version N]' \
    '       bootstrap-vault-kv.sh --env uat|prod --workspace ALIAS --purpose notify --object ID [--rotate --expected-version N]' \
    'Requires: vault CLI, VAULT_ADDR, and an existing Vault login (VAULT_TOKEN or CLI token helper).' \
    'Prompts for the credential without echo. Creates KV v2 records with CAS=0 by default.' \
    'notify stores the notify object opt_set JSON (webhook/secret/recipients) for Terraform.'
}

environment='' workspace='' purpose='' object='' rotate=false expected_version=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env|--workspace|--purpose|--object|--expected-version)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      case "$1" in
        --env) environment="$2" ;;
        --workspace) workspace="$2" ;;
        --purpose) purpose="$2" ;;
        --object) object="$2" ;;
        --expected-version) expected_version="$2" ;;
      esac
      shift 2 ;;
    --rotate) rotate=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[[ "$environment" == uat || "$environment" == prod ]] || { usage >&2; exit 2; }
[[ "$workspace" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { printf 'Invalid workspace alias.\n' >&2; exit 2; }
suffix=''
case "$purpose" in
  management|query) field=api_key ;;
  ingest) field=workspace_token ;;
  notify)
    field=opt_set
    [[ "$object" =~ ^[a-z][a-z0-9_]*$ ]] || { printf 'notify requires --object ID (lowercase HCL identifier).\n' >&2; exit 2; }
    suffix="/$object" ;;
  *) usage >&2; exit 2 ;;
esac
if [[ "$purpose" != notify && -n "$object" ]]; then
  printf '%s\n' '--object is only valid with --purpose notify.' >&2
  exit 2
fi
cas=0
if [[ "$rotate" == true ]]; then
  [[ "$expected_version" =~ ^[1-9][0-9]*$ ]] || { printf 'Rotation requires a positive --expected-version.\n' >&2; exit 2; }
  cas="$expected_version"
elif [[ -n "$expected_version" ]]; then
  printf '%s\n' '--expected-version requires --rotate.' >&2
  exit 2
fi
command -v vault >/dev/null || { printf 'vault CLI is required.\n' >&2; exit 1; }
[[ -n "${VAULT_ADDR:-}" ]] || { printf 'VAULT_ADDR is required.\n' >&2; exit 1; }
[[ -t 0 ]] || { printf 'Run interactively to enter the credential securely.\n' >&2; exit 1; }
secret_path="$environment/platform/observability/guance/$workspace/$purpose$suffix"
printf 'Vault target: %s\nKV record: kv/%s\nCAS version: %s\n' "$VAULT_ADDR" "$secret_path" "$cas"
read -r -p 'Type the environment name to confirm: ' confirmation
[[ "$confirmation" == "$environment" ]] || { printf 'Cancelled.\n' >&2; exit 1; }
credential=''
trap 'unset credential' EXIT
read -r -s -p "Enter $field: " credential
printf '\n'
[[ -n "$credential" ]] || { printf 'Credential cannot be empty.\n' >&2; exit 1; }
if [[ "$purpose" == notify ]]; then
  # Structure check only; the value is read from stdin and never echoed.
  printf '%s' "$credential" | python3 -c 'import json,sys; assert isinstance(json.load(sys.stdin), dict)' >/dev/null 2>&1 \
    || { printf 'opt_set must be a JSON object.\n' >&2; exit 1; }
fi
# Pass the value through stdin rather than exposing it in process arguments.
# Suppress Vault output, including server errors, to avoid credential disclosure.
if ! printf '%s' "$credential" | vault kv put -mount=kv -cas="$cas" "$secret_path" "$field=-" >/dev/null 2>&1; then
  printf 'Write failed. Check Vault authentication, KV v2 mount, policy, and expected version.\n' >&2
  exit 1
fi
unset credential
printf 'Stored %s at kv/%s. No credential value was printed.\n' "$field" "$secret_path"
