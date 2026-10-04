#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# destroy 之前核对: 这个 workspace 的 state 是否真的覆盖了本次 profile 声明的
# 那些实例。
#
# 为什么需要: terraform destroy 只销毁 state 里有的东西。选错 profile 时它会
# 打在一个空 workspace 上, 输出 "Destroy complete! Resources: 0 destroyed." 并
# 以成功退出 —— 机器还在跑、还在计费, 流水线却是绿的。2026-08-06 就是这样:
# 一次 destroy 落在 ...-web-saas, 真实资源在 ...-web-saas-agent-proxy, 没人
# 发现, 直到几小时后 plan 因为孤儿 state 崩掉才暴露出来。
#
# 判据是"云上有没有本 profile 声明的实例", 不是"state 空不空":
#   - state 有资源                     -> 正常 destroy。
#   - state 空, 云上也没有对应 label   -> 真的已经销毁干净了, 放行(重复
#                                          destroy 必须保持幂等)。
#   - state 空, 云上却有对应 label     -> 假绿, 硬失败并报出实例 ID。
# Vultr/Akamai 的 label 取自 render 阶段落盘的 hosts_manifest.json；AWS 的
# 渲染器不生成这个云厂商专用文件，因此改为从 terraform.auto.tfvars.json 读取
# name_prefix，并用 Tag_<name_prefix> 查询 EC2。三条路径都不依赖 apply 后的 CMDB。
# -----------------------------------------------------------------------------

: "${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE:?terraform workspace is required}"
: "${ENV_STEPS_ROUTE_OUTPUTS_STATE_KEY:?terraform state key is required}"
: "${ENV_STEPS_ROUTE_OUTPUTS_CLOUD_PROVIDER:=vultr-vps}"

state_json="$(terraform show -json 2>/dev/null || echo '{}')"
case "${ENV_STEPS_ROUTE_OUTPUTS_CLOUD_PROVIDER}" in
  aws-cloud)
    managed_resource_type="aws_instance"
    ;;
  vultr-vps)
    managed_resource_type="vultr_instance"
    ;;
  akamai-cloud)
    managed_resource_type="linode_instance"
    ;;
  *)
    echo "::error::unsupported destroy scope provider: ${ENV_STEPS_ROUTE_OUTPUTS_CLOUD_PROVIDER}" >&2
    exit 1
    ;;
esac

managed_instances="$(
  jq -r --arg resource_type "${managed_resource_type}" '
    def resources: .. | objects | select(has("resources")) | .resources[];
    [ (.values.root_module? // empty) | resources ]
    | map(select(.mode == "managed" and .type == $resource_type))
    | length
  ' <<<"${state_json}"
)"

# Akamai Cloud destroy is restricted to the labels in the current rendered
# manifest. The legacy observability host is a retained migration source and
# rollback point; it is never an eligible Terraform target in this workflow.
if [[ "${ENV_STEPS_ROUTE_OUTPUTS_CLOUD_PROVIDER}" == "akamai-cloud" ]]; then
  state_path="${ENV_STEPS_ROUTE_OUTPUTS_STATE_KEY%/terraform.tfstate}"
  namespace="${state_path##*/}"
  case "${namespace}" in
    web-saas|open-platform|ai-workspace|agent-proxy-jp|agent-proxy-us|agent-proxy-sg) ;;
    selfhost|all)
      echo "::error::Refusing aggregate Akamai destroy namespace '${namespace}'; use one isolated namespace." >&2
      exit 1
      ;;
    *)
      echo "::error::Refusing Akamai destroy for non-allowlisted namespace '${namespace}'." >&2
      exit 1
      ;;
  esac

  if [[ "${ENV_STEPS_ROUTE_OUTPUTS_STATE_KEY}" != terraform/uat/svc.plus/akamai-cloud/*/"${namespace}"/terraform.tfstate ]]; then
    echo "::error::Refusing Akamai UAT destroy: state key is not in the canonical five-level namespace." >&2
    exit 1
  fi

  if [[ "${namespace}" == "open-platform" ]]; then
    : "${OPEN_PLATFORM_ACCEPTANCE_FILE:=${GITHUB_WORKSPACE:-.}/config/open-platform-uat-cleanup-acceptance.json}"
    if [[ ! -f "${OPEN_PLATFORM_ACCEPTANCE_FILE}" ]] || ! jq -e '
        .environment == "uat" and
        .namespace == "open-platform" and
        .migration_complete == true and
        .source_unchanged_through_acceptance == true and
        .target_health_checks_passed == true and
        .source_health_checks_passed == true and
        .state_isolation_verified == true and
        (.backup_reference | type == "string" and length > 0) and
        (.acceptance_reference | type == "string" and length > 0)
      ' "${OPEN_PLATFORM_ACCEPTANCE_FILE}" >/dev/null 2>&1; then
      echo "::error::Refusing UAT cleanup until migration, dual-end health, source-retention and six-state isolation acceptance are recorded." >&2
      exit 1
    fi
  fi

  : "${HOSTS_MANIFEST:=hosts_manifest.json}"
  [[ -f "${HOSTS_MANIFEST}" ]] || {
    echo "::error::${HOSTS_MANIFEST} is missing; render the selected profile before asserting Akamai destroy scope." >&2
    exit 1
  }
  mapfile -t expected_labels < <(jq -r '.hosts[]?.label | select(. != "")' "${HOSTS_MANIFEST}")
  mapfile -t state_labels < <(jq -r '
    def resources: .. | objects | select(has("resources")) | .resources[];
    [ (.values.root_module? // empty) | resources ]
    | .[] | select(.mode == "managed" and .type == "linode_instance")
    | .values.label // empty
  ' <<<"${state_json}")
  IFS=',' read -r -a protected_source_labels <<<"${PROTECTED_EXTERNAL_INSTANCE_LABELS:-observability.svc.plus}"

  is_protected_source_label() {
    local candidate="$1" protected
    for protected in "${protected_source_labels[@]}"; do
      [[ -n "${protected}" && "${candidate}" == "${protected}" ]] && return 0
    done
    return 1
  }

  for label in "${expected_labels[@]}"; do
    if is_protected_source_label "${label}"; then
      echo "::error::Refusing Akamai destroy: protected migration source label '${label}' is present in the Terraform manifest." >&2
      exit 1
    fi
    if [[ "${namespace}" != "open-platform" && "${label}" == *open-platform* ]]; then
      echo "::error::Refusing Akamai destroy: permanent open-platform label '${label}' is present in the Terraform manifest." >&2
      exit 1
    fi
  done
  if [[ "${#state_labels[@]}" -ne "${managed_instances}" ]]; then
    echo "::error::Refusing Akamai destroy: one or more managed Linode instances have no verifiable label in state." >&2
    exit 1
  fi
  for label in "${state_labels[@]}"; do
    if is_protected_source_label "${label}"; then
      echo "::error::Refusing Akamai destroy: protected migration source '${label}' appears in Terraform state." >&2
      exit 1
    fi
    if [[ "${namespace}" != "open-platform" && "${label}" == *open-platform* ]]; then
      echo "::error::Refusing Akamai destroy: permanent open-platform resource '${label}' appears in Terraform state." >&2
      exit 1
    fi
    expected_match=false
    for expected_label in "${expected_labels[@]}"; do
      if [[ "${label}" == "${expected_label}" ]]; then
        expected_match=true
        break
      fi
    done
    if [[ "${expected_match}" != true ]]; then
      echo "::error::Refusing Akamai destroy: state instance '${label}' is outside the selected profile manifest." >&2
      exit 1
    fi
  done
fi

if [[ "${managed_instances}" -gt 0 ]]; then
  echo "Destroy scope: workspace ${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE} manages ${managed_instances} verified in-profile instance(s); proceeding."
  exit 0
fi

if [[ "${ENV_STEPS_ROUTE_OUTPUTS_CLOUD_PROVIDER}" == "aws-cloud" ]]; then
  : "${AWS_DESTROY_REGIONS:=${AWS_REGION:-ap-northeast-1}}"
  terraform_vars="terraform.auto.tfvars.json"
  [[ -f "${terraform_vars}" ]] || {
    echo "::error::${terraform_vars} is missing; run generate.py render before asserting AWS destroy scope." >&2
    exit 1
  }

  name_prefix="$(jq -r '.name_prefix // empty' "${terraform_vars}")"
  [[ -n "${name_prefix}" ]] || {
    echo "::error::AWS destroy scope cannot determine name_prefix from ${terraform_vars}." >&2
    exit 1
  }

  IFS=',' read -r -a regions <<<"${AWS_DESTROY_REGIONS}"
  stray=()
  for region in "${regions[@]}"; do
    [[ -n "${region}" ]] || continue
    matches="$(aws ec2 describe-instances \
      --region "${region}" \
      --filters \
        "Name=tag:Tag_${name_prefix},Values=true" \
        'Name=instance-state-name,Values=pending,running,stopping,stopped' \
      --query 'Reservations[].Instances[].{id:InstanceId,ip:PublicIpAddress,state:State.Name}' \
      --output json)"
    while IFS=$'\t' read -r instance_id public_ip state; do
      [[ -n "${instance_id}" ]] || continue
      stray+=("${region}: ${instance_id} (${state}, ${public_ip:-no-public-ip})")
    done < <(jq -r '.[]? | [.id, (.ip // ""), .state] | @tsv' <<<"${matches}")
  done

  if [[ "${#stray[@]}" -eq 0 ]]; then
    echo "Destroy scope: state is empty and AWS has no EC2 instance tagged Tag_${name_prefix}=true; already destroyed."
    exit 0
  fi

  {
    echo "::error::Refusing to report a successful destroy that would delete nothing."
    echo "Workspace ${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE} (state ${ENV_STEPS_ROUTE_OUTPUTS_STATE_KEY}) manages no instances, but AWS still has ${#stray[@]} EC2 instance(s) matching Tag_${name_prefix}=true:"
    printf '  - %s\n' "${stray[@]}"
    echo "They belong to a different workspace/state. Re-run destroy with the target_domains value that created them, or adopt them into this state first."
  } >&2
  exit 1
fi

if [[ "${ENV_STEPS_ROUTE_OUTPUTS_CLOUD_PROVIDER}" == "akamai-cloud" ]]; then
  : "${LINODE_TOKEN:?LINODE_TOKEN is required for Akamai Cloud destroy scope checks}"
  : "${HOSTS_MANIFEST:=hosts_manifest.json}"

  [[ -f "${HOSTS_MANIFEST}" ]] || {
    echo "::error::${HOSTS_MANIFEST} is missing; run generate.py render before asserting Akamai destroy scope." >&2
    exit 1
  }

  mapfile -t expected_labels < <(jq -r '.hosts[]?.label | select(. != "")' "${HOSTS_MANIFEST}")
  if [[ "${#expected_labels[@]}" -eq 0 ]]; then
    echo "Destroy scope: this Akamai profile declares no hosts; nothing to destroy."
    exit 0
  fi

  instances="$(curl -fsS --retry 3 --retry-connrefused \
    -H "Authorization: Bearer ${LINODE_TOKEN}" \
    'https://api.linode.com/v4/linode/instances?page_size=500')"

  stray=()
  for label in "${expected_labels[@]}"; do
    match="$(jq -r --arg l "${label}" \
      '.data[]? | select(.label == $l) | "\(.id) (\(.ipv4[0] // \"no-public-ip\"))"' <<<"${instances}")"
    [[ -n "${match}" ]] && stray+=("${label} -> ${match}")
  done

  if [[ "${#stray[@]}" -eq 0 ]]; then
    echo "Destroy scope: state is empty and Akamai Cloud has no instance matching this profile's labels; already destroyed."
    exit 0
  fi

  {
    echo "::error::Refusing to report a successful destroy that would delete nothing."
    echo "Workspace ${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE} (state ${ENV_STEPS_ROUTE_OUTPUTS_STATE_KEY}) manages no instances, but Akamai Cloud still has ${#stray[@]} instance(s) declared by this profile:"
    printf '  - %s\n' "${stray[@]}"
    echo "They belong to a different workspace/state. Re-run destroy with the target_domains value that created them, or adopt them into this state first."
  } >&2
  exit 1
fi

: "${VULTR_API_KEY:?VULTR_API_KEY is required for Vultr destroy scope checks}"
: "${HOSTS_MANIFEST:=hosts_manifest.json}"

[[ -f "${HOSTS_MANIFEST}" ]] || {
  echo "::error::${HOSTS_MANIFEST} is missing; run generate.py render before asserting Vultr destroy scope." >&2
  exit 1
}

mapfile -t expected_labels < <(jq -r '.hosts[]?.label | select(. != "")' "${HOSTS_MANIFEST}")
if [[ "${#expected_labels[@]}" -eq 0 ]]; then
  echo "Destroy scope: this profile declares no hosts; nothing to destroy."
  exit 0
fi

instances="$(curl -fsS --retry 3 --retry-connrefused \
  -H "Authorization: Bearer ${VULTR_API_KEY}" \
  'https://api.vultr.com/v2/instances?per_page=500')"

stray=()
for label in "${expected_labels[@]}"; do
  match="$(jq -r --arg l "${label}" \
    '.instances[]? | select(.label == $l) | "\(.id) (\(.main_ip))"' <<<"${instances}")"
  [[ -n "${match}" ]] && stray+=("${label} -> ${match}")
done

if [[ "${#stray[@]}" -eq 0 ]]; then
  echo "Destroy scope: state is empty and Vultr has no instance matching this profile's labels; already destroyed."
  exit 0
fi

{
  echo "::error::Refusing to report a successful destroy that would delete nothing."
  echo "Workspace ${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE} (state ${ENV_STEPS_ROUTE_OUTPUTS_STATE_KEY}) manages no instances, but Vultr still has ${#stray[@]} instance(s) declared by this profile:"
  printf '  - %s\n' "${stray[@]}"
  echo "They belong to a different workspace/state. Re-run destroy with the target_domains value that created them, or adopt them into this state first."
} >&2
exit 1
