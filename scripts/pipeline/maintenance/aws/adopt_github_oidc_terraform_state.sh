#!/usr/bin/env bash
set -euo pipefail

readonly expected_account_id="950604983695"
readonly expected_role_name="GithubAction_IAC_Deploy_Role"
readonly expected_policy_arn="arn:aws:iam::aws:policy/AdministratorAccess"
readonly expected_provider_url="token.actions.githubusercontent.com"
readonly expected_state_key="platform-ops-toolkit/prod/aws-cloud/bootstrap/identity/terraform.tfstate"

iac_root="${IAC_MODULES_ROOT:?IAC_MODULES_ROOT is required}"
gitops_config="${GITOPS_AWS_OIDC_CONFIG:?GITOPS_AWS_OIDC_CONFIG is required}"
bootstrap_config="${IAC_BOOTSTRAP_CONFIG:?IAC_BOOTSTRAP_CONFIG is required}"
terraform_dir="${iac_root}/terraform-hcl-standard/aws-cloud/bootstrap/identity"

for command in aws jq ruby terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "${command} is required for Terraform state adoption" >&2
    exit 1
  }
done

for file in "${gitops_config}" "${bootstrap_config}"; do
  test -f "${file}" || {
    echo "Required state-adoption configuration is missing: ${file}" >&2
    exit 1
  }
done

test -d "${terraform_dir}" || {
  echo "AWS identity Terraform module is missing: ${terraform_dir}" >&2
  exit 1
}

for required in TF_STATE_ENDPOINT TF_STATE_BUCKET TF_STATE_ACCESS_KEY TF_STATE_SECRET_KEY TF_STATE_REGION; do
  test -n "${!required:-}" || {
    echo "Vault iac_state must include ${required}." >&2
    exit 1
  }
done

jq -e \
  --arg account_id "${expected_account_id}" \
  --arg role_name "${expected_role_name}" \
  --arg policy_arn "${expected_policy_arn}" '
  .apiVersion == "gitops.svc.plus/v1alpha1" and
  .kind == "GitHubActionsOIDCConfig" and
  .metadata.environment == "prod" and
  .spec.provider_url == "https://token.actions.githubusercontent.com" and
  .spec.audience == "sts.amazonaws.com" and
  .spec.aws.account_id == $account_id and
  .spec.aws.role_name == $role_name and
  .spec.aws.role_arn == ("arn:aws:iam::" + $account_id + ":role/" + $role_name) and
  (.spec.subjects | index("repo:ai-workspace-infra/platform-ops-toolkit:environment:production"))
' "${gitops_config}" >/dev/null || {
  echo "GitOps OIDC declaration failed the Terraform state-adoption contract." >&2
  exit 1
}

state_key="$(ruby -ryaml -e 'puts YAML.load_file(ARGV.fetch(0)).dig("terraform_state", "key")' "${bootstrap_config}")"
test "${state_key}" = "${expected_state_key}" || {
  echo "Unexpected Terraform state key: ${state_key}." >&2
  exit 1
}

caller_account="$(aws sts get-caller-identity --query Account --output text)"
caller_arn="$(aws sts get-caller-identity --query Arn --output text)"
test "${caller_account}" = "${expected_account_id}" || {
  echo "OIDC credentials belong to AWS account ${caller_account}, expected ${expected_account_id}." >&2
  exit 1
}
test "${caller_arn}" = "arn:aws:sts::${expected_account_id}:assumed-role/${expected_role_name}/platform-ops-oidc-state-adoption" || {
  echo "Terraform state adoption must use ${expected_role_name} via GitHub OIDC, got ${caller_arn}." >&2
  exit 1
}

export TF_VAR_bootstrap_config_path="${bootstrap_config}"
export TF_VAR_github_actions_oidc_config_path="${gitops_config}"

backend_config="$(mktemp)"
trap 'rm -f "${backend_config}"' EXIT
umask 077
cat > "${backend_config}" <<EOF
endpoint = "${TF_STATE_ENDPOINT}"
bucket = "${TF_STATE_BUCKET}"
key = "${state_key}"
region = "${TF_STATE_REGION}"
access_key = "${TF_STATE_ACCESS_KEY}"
secret_key = "${TF_STATE_SECRET_KEY}"
skip_credentials_validation = true
skip_region_validation = true
skip_requesting_account_id = true
skip_metadata_api_check = true
skip_s3_checksum = true
force_path_style = true
EOF

terraform -chdir="${terraform_dir}" init -input=false -reconfigure -backend-config="${backend_config}"

adopt_if_missing() {
  local address="$1" import_id="$2"
  if terraform -chdir="${terraform_dir}" state show -no-color "${address}" >/dev/null 2>&1; then
    echo "Terraform state already manages ${address}."
    return
  fi

  terraform -chdir="${terraform_dir}" import -input=false "${address}" "${import_id}"
  terraform -chdir="${terraform_dir}" state show -no-color "${address}" >/dev/null
  echo "Imported ${address} into ${state_key}."
}

provider_arn="arn:aws:iam::${expected_account_id}:oidc-provider/${expected_provider_url}"
adopt_if_missing "aws_iam_openid_connect_provider.github_actions" "${provider_arn}"
adopt_if_missing "aws_iam_role.github_actions_deploy_role" "${expected_role_name}"
adopt_if_missing \
  "aws_iam_role_policy_attachment.github_actions_deploy_role_admin" \
  "${expected_role_name}/${expected_policy_arn}"

set +e
terraform -chdir="${terraform_dir}" plan \
  -input=false \
  -detailed-exitcode \
  -var="bootstrap_config_path=${bootstrap_config}" \
  -var="github_actions_oidc_config_path=${gitops_config}" \
plan_status=$?
set -e

case "${plan_status}" in
  0)
    echo "Terraform state adoption complete: the GitHub OIDC resources match IaC."
    ;;
  2)
    echo "Terraform state adoption found drift in the fixed GitHub OIDC resources; no Terraform apply was performed." >&2
    exit 1
    ;;
  *)
    echo "Terraform state adoption plan failed with exit code ${plan_status}." >&2
    exit "${plan_status}"
    ;;
esac
