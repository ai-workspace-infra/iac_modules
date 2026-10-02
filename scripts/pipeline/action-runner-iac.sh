#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

load_common_env() {
  # shellcheck source=lib/require-env.sh
  . "${script_dir}/lib/require-env.sh"
}

generate_render() {
  load_common_env
  require_env VAULT_ENV_PATH

  VAULT_ENV_PATH="${VAULT_ENV_PATH:-uat}"
  python3 scripts/generate.py render \
    --resources "config/resources/${VAULT_ENV_PATH}/action-runner.yaml" \
    --workdir "envs/action-runner"
}

terraform_init() {
  load_common_env
  require_env VAULT_ENV_PATH TF_STATE_ENDPOINT TF_STATE_BUCKET TF_STATE_ACCESS_KEY TF_STATE_SECRET_KEY TF_STATE_REGION

  VAULT_ENV_PATH="${VAULT_ENV_PATH:-uat}"
  terraform init -input=false \
    -backend-config="endpoint=${TF_STATE_ENDPOINT}" \
    -backend-config="bucket=${TF_STATE_BUCKET}" \
    -backend-config="key=terraform/${VAULT_ENV_PATH}/platform-ops-toolkit/vultr-vps/primary/action-runner/terraform.tfstate" \
    -backend-config="access_key=${TF_STATE_ACCESS_KEY}" \
    -backend-config="secret_key=${TF_STATE_SECRET_KEY}" \
    -backend-config="region=${TF_STATE_REGION}" \
    -backend-config="skip_credentials_validation=true" \
    -backend-config="skip_metadata_api_check=true" \
    -backend-config="skip_region_validation=true" \
    -backend-config="use_path_style=true" \
    -backend-config="use_lockfile=true"
}

terraform_action() {
  load_common_env
  require_env TERRAFORM_ACTION

  TERRAFORM_ACTION="${TERRAFORM_ACTION:-apply}"
  terraform "${TERRAFORM_ACTION}" -auto-approve -input=false
}

generate_inventory() {
  load_common_env
  require_env VAULT_ENV_PATH

  VAULT_ENV_PATH="${VAULT_ENV_PATH:-uat}"
  python3 scripts/generate.py inventory \
    --resources "config/resources/${VAULT_ENV_PATH}/action-runner.yaml" \
    --workdir "envs/action-runner"
}

build_matrix() {
  local hosts count
  if [[ -f cmdb.json ]]; then
    hosts="$(jq -c 'keys' cmdb.json)"
    count="$(jq 'length' cmdb.json)"
  else
    hosts='[]'
    count='0'
  fi

  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "hosts=${hosts}" >>"${GITHUB_OUTPUT}"
    echo "count=${count}" >>"${GITHUB_OUTPUT}"
  else
    echo "hosts=${hosts}"
    echo "count=${count}"
  fi
}

usage() {
  echo "Usage: ${BASH_SOURCE[0]} {render|terraform-init|terraform-action|inventory|build-matrix}" >&2
  exit 2
}

case "${1:-}" in
  render) generate_render ;;
  terraform-init) terraform_init ;;
  terraform-action) terraform_action ;;
  inventory) generate_inventory ;;
  build-matrix) build_matrix ;;
  *) usage ;;
esac
