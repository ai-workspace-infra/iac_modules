#!/bin/bash
set -euo pipefail

# S3 state keys already isolate the UAT Akamai namespaces.  The six namespace
# states were created in Terraform's default workspace; selecting a second
# workspace here would make an otherwise populated backend appear empty and
# cause a duplicate create plan.  Keep the named workspace for providers whose
# backend contract uses workspaces (for example Vultr), but never layer it on
# top of an Akamai namespace key.
if [[ "${ENV_STEPS_ROUTE_OUTPUTS_CLOUD_PROVIDER:-}" != "akamai-cloud" ]]; then
  terraform workspace select -or-create "${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE}"
fi

ACTION="${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_ACTION}"
case "${ACTION}" in
  plan)
    terraform plan -input=false
    ;;
  apply)
    plan_file="${RUNNER_TEMP:-/tmp}/platform-ops-${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE}.tfplan"
    plan_json="${plan_file}.json"
    terraform plan -input=false -out="${plan_file}"
    terraform show -json "${plan_file}" > "${plan_json}"

    # A normal UAT deploy may create or update resources, but must never
    # implicitly destroy/recreate them (including ForceNew replacements).
    if [[ "${ENV_STEPS_ROUTE_OUTPUTS_STATE_KEY:-}" == terraform/uat/* ]] && \
      jq -e '[.resource_changes[]? | select(.change.actions | index("delete"))] | length > 0' \
        "${plan_json}" >/dev/null; then
      echo '::error::UAT apply plan contains a delete or replacement. Reconcile drift before applying.' >&2
      exit 1
    fi

    downgrade_count="$(jq '
      def rank:
        if . == "vc2-1c-1gb" then 1
        elif . == "vc2-1c-2gb" then 2
        elif . == "vc2-2c-4gb" then 3
        elif . == "vc2-4c-8gb" then 4
        else 0
        end;
      [ .resource_changes[]?
        | select(.type == "vultr_instance")
        | select(.change.actions == ["update"])
        | .change as $change
        | ($change.before.plan | rank) as $before
        | ($change.after.plan | rank) as $after
        | select($before > $after and $after > 0)
      ] | length
    ' "${plan_json}")"

    if [[ "${downgrade_count}" != 0 ]]; then
      echo "::error::Vultr does not support in-place VPS downgrades. Re-run platform-ops with action=resize so the guarded replacement workflow can snapshot, validate, adopt state, and deploy the new instance." >&2
      exit 1
    fi

    terraform apply -input=false -auto-approve "${plan_file}"
    ;;
  destroy)
    # 空 workspace 上的 destroy 会输出 "0 destroyed" 并成功退出。断言这不是
    # 选错 profile 造成的假绿 —— 机器还在跑、还在计费, 流水线却是绿的。
    "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/assert-destroy-scope.sh"
    terraform destroy -auto-approve -input=false
    ;;
  *)
    echo "::error::unsupported terraform action: ${ACTION}" >&2
    exit 1
    ;;
esac
