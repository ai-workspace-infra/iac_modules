#!/usr/bin/env bash
set -euo pipefail

action="${BOOTSTRAP_ACTION:?BOOTSTRAP_ACTION is required}"
config_file="${GITOPS_AWS_OIDC_CONFIG:?GITOPS_AWS_OIDC_CONFIG is required}"
deployment_env="${DEPLOYMENT_ENV:-prod}"
readonly expected_repository="ai-workspace-infra/platform-ops-toolkit"
readonly deploy_role_policy_arn="arn:aws:iam::aws:policy/AdministratorAccess"
readonly github_actions_thumbprint="6938fd4d98bab03faadb97b34396831e3780aea1"
readonly allowed_iam_actions="iam:ListOpenIDConnectProviders, iam:GetOpenIDConnectProvider, iam:CreateOpenIDConnectProvider, iam:AddClientIDToOpenIDConnectProvider, iam:UpdateOpenIDConnectProviderThumbprint, iam:GetRole, iam:CreateRole, iam:ListAttachedRolePolicies, iam:AttachRolePolicy, iam:TagRole, iam:UpdateAssumeRolePolicy"

case "${action}" in
  plan|apply) ;;
  *)
    echo "BOOTSTRAP_ACTION must be plan or apply, got: ${action}" >&2
    exit 1
    ;;
esac

case "${deployment_env}" in
  uat) expected_github_environment="uat" ;;
  prod) expected_github_environment="production" ;;
  *) echo "DEPLOYMENT_ENV must be uat or prod, got: ${deployment_env}" >&2; exit 1 ;;
esac

for command in aws jq; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "${command} is required for AWS OIDC bootstrap recovery" >&2
    exit 1
  }
done

test -f "${config_file}" || {
  echo "GitOps AWS OIDC declaration not found: ${config_file}" >&2
  exit 1
}

test -n "${AWS_ACCESS_KEY_ID:-}" && test -n "${AWS_SECRET_ACCESS_KEY:-}" || {
  echo "Vault aws-bootstrap credentials must include AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY." >&2
  exit 1
}

jq -e --arg repository "${expected_repository}" --arg environment "${deployment_env}" --arg github_environment "${expected_github_environment}" '
  .apiVersion == "gitops.svc.plus/v1alpha1" and
  .kind == "GitHubActionsOIDCConfig" and
  .metadata.environment == $environment and
  .metadata.provider == "aws" and
  .spec.provider_url == "https://token.actions.githubusercontent.com" and
  .spec.audience == "sts.amazonaws.com" and
  (.spec.aws.account_id | test("^[0-9]{12}$")) and
  (.spec.aws.role_name | test("^[A-Za-z0-9+=,.@_-]+$")) and
  .spec.aws.role_arn == ("arn:aws:iam::" + .spec.aws.account_id + ":role/" + .spec.aws.role_name) and
  (.spec.subjects | type == "array") and
  (.spec.subjects | index("repo:" + $repository + ":ref:refs/heads/main")) and
  (.spec.subjects | index("repo:" + $repository + ":environment:" + $github_environment)) and
  (if $environment == "prod" then (.spec.subjects | index("repo:" + $repository + ":ref:refs/tags/v*")) else true end)
' "${config_file}" >/dev/null || {
  echo "GitOps AWS OIDC declaration failed the ${deployment_env} recovery contract." >&2
  exit 1
}

account_id="$(jq -er '.spec.aws.account_id' "${config_file}")"
role_name="$(jq -er '.spec.aws.role_name' "${config_file}")"
role_arn="$(jq -er '.spec.aws.role_arn' "${config_file}")"
provider_url="$(jq -er '.spec.provider_url' "${config_file}")"
audience="$(jq -er '.spec.audience' "${config_file}")"
subjects="$(jq -ec '.spec.subjects' "${config_file}")"
provider_host="${provider_url#https://}"
provider_arn="arn:aws:iam::${account_id}:oidc-provider/${provider_host}"

if [ -n "${GITHUB_ENV:-}" ]; then
  printf 'GITHUB_ACTIONS_DEPLOY_ROLE_ARN=%s\n' "${role_arn}" >> "${GITHUB_ENV}"
fi
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  printf 'role_arn=%s\n' "${role_arn}" >> "${GITHUB_OUTPUT}"
fi

caller_identity="$(aws sts get-caller-identity --output json)"
caller_account="$(jq -er '.Account' <<<"${caller_identity}")"
caller_arn="$(jq -er '.Arn' <<<"${caller_identity}")"
test "${caller_account}" = "${account_id}" || {
  echo "Bootstrap credentials belong to AWS account ${caller_account}, expected ${account_id}." >&2
  exit 1
}

if [ "${caller_arn}" = "arn:aws:iam::${account_id}:root" ]; then
  if [ "${action}" = "apply" ] && [ -z "${AWS_SESSION_TOKEN:-}" ]; then
    echo "Root recovery apply requires temporary session credentials; static root keys are rejected." >&2
    exit 1
  fi
  echo "::warning::Using a root-principal break-glass session. Root permissions cannot be scope-limited; this workflow is limited by its Vault JWT binding, Production approval, explicit confirmation, and short credential lifetime."
  if [ "${action}" = "apply" ] && [ "${ALLOW_ROOT_BREAK_GLASS:-false}" != "true" ]; then
    echo "Refusing apply with root-principal credentials until allow_root_break_glass=true is explicitly supplied." >&2
    exit 1
  fi
fi

echo "AWS bootstrap workflow API scope: ${allowed_iam_actions}."

role_exists=false
role_needs_admin_policy=false
role_details="$(aws iam get-role --role-name "${role_name}" 2>&1)" || {
  if ! grep -Fq 'NoSuchEntity' <<<"${role_details}"; then
    printf '%s\n' "${role_details}" >&2
    exit 1
  fi
  role_details=""
}

if [ -n "${role_details}" ]; then
  role_exists=true
  role_actual_arn="$(jq -er '.Role.Arn' <<<"${role_details}")"
  test "${role_actual_arn}" = "${role_arn}" || {
    echo "Existing role ARN does not match GitOps declaration: ${role_actual_arn}." >&2
    exit 1
  }

  attached_policy_arns="$(aws iam list-attached-role-policies \
    --role-name "${role_name}" \
    --query 'AttachedPolicies[].PolicyArn' \
    --output json)"
  if ! jq -e --arg policy_arn "${deploy_role_policy_arn}" \
    'index($policy_arn) != null' <<<"${attached_policy_arns}" >/dev/null; then
    role_needs_admin_policy=true
  fi
fi

provider_arns="$(aws iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[].Arn' --output json)"
provider_exists=false
provider_needs_audience=false
provider_needs_thumbprint=false

if jq -e --arg provider_arn "${provider_arn}" 'index($provider_arn) != null' <<<"${provider_arns}" >/dev/null; then
  provider_exists=true
  provider_details="$(aws iam get-open-id-connect-provider --open-id-connect-provider-arn "${provider_arn}")"

  jq -e --arg provider_host "${provider_host}" '.Url == $provider_host' <<<"${provider_details}" >/dev/null || {
    echo "Existing OIDC provider URL does not match GitOps declaration: ${provider_arn}." >&2
    exit 1
  }

  if ! jq -e --arg audience "${audience}" '.ClientIDList | index($audience) != null' <<<"${provider_details}" >/dev/null; then
    provider_needs_audience=true
  fi
  if ! jq -e --arg thumbprint "${github_actions_thumbprint}" '.ThumbprintList | index($thumbprint) != null' <<<"${provider_details}" >/dev/null; then
    provider_needs_thumbprint=true
  fi
fi

policy_file="$(mktemp)"
trap 'rm -f "${policy_file}"' EXIT
jq -n \
  --arg provider_arn "${provider_arn}" \
  --arg audience "${audience}" \
  --argjson subjects "${subjects}" '
  {
    Version: "2012-10-17",
    Statement: [{
      Effect: "Allow",
      Principal: {Federated: $provider_arn},
      Action: "sts:AssumeRoleWithWebIdentity",
      Condition: {
        StringEquals: {"token.actions.githubusercontent.com:aud": $audience},
        StringLike: {"token.actions.githubusercontent.com:sub": $subjects}
      }
    }]
  }
' > "${policy_file}"

echo "Validated GitOps OIDC declaration, AWS account, and target role."
echo "Permitted subjects: $(jq -r '.[]' <<<"${subjects}" | paste -sd ', ' -)"

if [ "${action}" = "plan" ]; then
  if [ "${provider_exists}" = false ]; then
    echo "Plan: would create OIDC provider ${provider_arn} with audience ${audience}."
  elif [ "${provider_needs_audience}" = true ]; then
    echo "Plan: would add audience ${audience} to OIDC provider ${provider_arn}."
  else
    echo "Plan: OIDC provider ${provider_arn} already matches GitOps."
  fi
  if [ "${provider_exists}" = false ] || [ "${provider_needs_thumbprint}" = true ]; then
    echo "Plan: would set GitHub OIDC thumbprint ${github_actions_thumbprint} on ${provider_arn}."
  fi
  if [ "${role_exists}" = false ]; then
    echo "Plan: would create ${role_name} with managed policy ${deploy_role_policy_arn}."
  elif [ "${role_needs_admin_policy}" = true ]; then
    echo "Plan: would attach managed policy ${deploy_role_policy_arn} to ${role_name}."
  else
    echo "Plan: ${role_name} already has managed policy ${deploy_role_policy_arn}."
  fi
  echo "Plan: would update ${role_name} trust policy from the GitOps declaration."
  echo "Plan: would reconcile Name and Environment=${deployment_env} tags on ${role_name}."
  echo "Plan complete. No AWS IAM change was made. Re-run with action=apply after reviewing this output."
  exit 0
fi

if [ "${provider_exists}" = false ]; then
  created_provider_arn="$(aws iam create-open-id-connect-provider \
    --url "${provider_url}" \
    --client-id-list "${audience}" \
    --thumbprint-list "${github_actions_thumbprint}" \
    --query 'OpenIDConnectProviderArn' \
    --output text)"
  test "${created_provider_arn}" = "${provider_arn}" || {
    echo "Created unexpected OIDC provider ARN: ${created_provider_arn}." >&2
    exit 1
  }
  echo "Created OIDC provider ${provider_arn}."
elif [ "${provider_needs_audience}" = true ]; then
  aws iam add-client-id-to-open-id-connect-provider \
    --open-id-connect-provider-arn "${provider_arn}" \
    --client-id "${audience}"
  echo "Added audience ${audience} to OIDC provider ${provider_arn}."
fi

if [ "${provider_exists}" = true ] && [ "${provider_needs_thumbprint}" = true ]; then
  aws iam update-open-id-connect-provider-thumbprint \
    --open-id-connect-provider-arn "${provider_arn}" \
    --thumbprint-list "${github_actions_thumbprint}"
  echo "Set GitHub OIDC thumbprint on ${provider_arn}."
fi

aws iam get-open-id-connect-provider --open-id-connect-provider-arn "${provider_arn}" >/dev/null

if [ "${role_exists}" = false ]; then
  created_role_arn="$(aws iam create-role \
    --role-name "${role_name}" \
    --assume-role-policy-document "file://${policy_file}" \
    --tags "Key=Name,Value=${role_name}" "Key=Environment,Value=${deployment_env}" \
    --query 'Role.Arn' \
    --output text)"
  test "${created_role_arn}" = "${role_arn}" || {
    echo "Created unexpected IAM role ARN: ${created_role_arn}." >&2
    exit 1
  }
  role_needs_admin_policy=true
  echo "Created ${role_name} from the GitOps trust policy."
fi

if [ "${role_needs_admin_policy}" = true ]; then
  aws iam attach-role-policy \
    --role-name "${role_name}" \
    --policy-arn "${deploy_role_policy_arn}"
  echo "Attached managed policy ${deploy_role_policy_arn} to ${role_name}."
fi

aws iam tag-role \
  --role-name "${role_name}" \
  --tags "Key=Name,Value=${role_name}" "Key=Environment,Value=${deployment_env}"
echo "Reconciled Name and Environment=${deployment_env} tags on ${role_name}."

aws iam update-assume-role-policy \
  --role-name "${role_name}" \
  --policy-document "file://${policy_file}"

echo "Updated ${role_name} trust policy from the GitOps declaration."
