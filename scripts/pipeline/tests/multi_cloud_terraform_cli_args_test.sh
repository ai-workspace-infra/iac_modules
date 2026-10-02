#!/usr/bin/env bash
set -euo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/multi-cloud-terraform-cli-args.sh"
workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT

expected() {
  printf '%s\n' "TF_CLI_ARGS_init=-backend-config=\"endpoint=https://s3.example.test\" -backend-config=\"bucket=state-bucket\" -backend-config=\"key=terraform/uat/svc.plus/aws-cloud/123456789012/$1-vpc/terraform.tfstate\" -backend-config=\"access_key=access\" -backend-config=\"secret_key=secret\" -backend-config=\"region=ap-northeast-1\" -backend-config=\"skip_credentials_validation=true\" -backend-config=\"skip_metadata_api_check=true\" -backend-config=\"skip_region_validation=true\" -backend-config=\"use_path_style=true\" -backend-config=\"use_lockfile=true\""
}

run() {
  VAULT_TF_STATE_ENDPOINT=https://s3.example.test VAULT_TF_STATE_BUCKET=state-bucket \
    VAULT_TF_STATE_ACCESS_KEY=access VAULT_TF_STATE_SECRET_KEY=secret VAULT_TF_STATE_REGION=ap-northeast-1 \
    DEPLOY_ENV=uat PROJECT=svc.plus CLOUD_PROVIDER=aws-cloud STATE_ACCOUNT=123456789012 MATRIX_COMPONENT=vpc \
    GITHUB_ENV="$1" "${script}" "${@:2}"
}

for scope in accounts resources; do
  run "${workdir}/${scope}.env" "${scope}"
  diff <(expected "${scope}") "${workdir}/${scope}.env" || {
    echo "TF_CLI_ARGS_init for ${scope} does not match the state backend contract" >&2
    exit 1
  }
done

# Anything else would silently write a state key into the wrong namespace.
for bad in "" account resource all; do
  if run "${workdir}/bad.env" ${bad:+"${bad}"} 2>/dev/null; then
    echo "scope '${bad}' must be rejected" >&2
    exit 1
  fi
  [[ ! -s "${workdir}/bad.env" ]] || { echo "a rejected scope must not write GITHUB_ENV" >&2; exit 1; }
done

echo "multi_cloud_terraform_cli_args_test: PASS"
