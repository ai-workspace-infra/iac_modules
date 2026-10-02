#!/bin/bash
# Usage: multi-cloud-terraform-cli-args.sh <accounts|resources>
#
# Exports TF_CLI_ARGS_init so that `make init` in a multi-cloud account or
# resources component uses the shared S3-compatible Terraform state backend.
# The two matrices share one backend contract and differ only in the state key
# segment: accounts-<component> versus resources-<component>.
case "${1:-}" in
  accounts|resources)
    STATE_SCOPE="$1"
    ;;
  *)
    echo "::error::usage: ${0##*/} <accounts|resources>" >&2
    exit 2
    ;;
esac

echo "TF_CLI_ARGS_init=-backend-config=\"endpoint=${VAULT_TF_STATE_ENDPOINT}\" -backend-config=\"bucket=${VAULT_TF_STATE_BUCKET}\" -backend-config=\"key=terraform/${DEPLOY_ENV}/${PROJECT}/${CLOUD_PROVIDER}/${STATE_ACCOUNT}/${STATE_SCOPE}-${MATRIX_COMPONENT}/terraform.tfstate\" -backend-config=\"access_key=${VAULT_TF_STATE_ACCESS_KEY}\" -backend-config=\"secret_key=${VAULT_TF_STATE_SECRET_KEY}\" -backend-config=\"region=${VAULT_TF_STATE_REGION}\" -backend-config=\"skip_credentials_validation=true\" -backend-config=\"skip_metadata_api_check=true\" -backend-config=\"skip_region_validation=true\" -backend-config=\"use_path_style=true\" -backend-config=\"use_lockfile=true\"" >> "$GITHUB_ENV"
