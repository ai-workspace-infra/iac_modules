#!/usr/bin/env bash
set -euo pipefail

: "${VULTR_API_KEY:?VULTR_API_KEY is required}"
: "${INSTANCE_ID:?INSTANCE_ID is required}"
: "${TARGET_PLAN:?TARGET_PLAN is required}"
: "${RESIZE_MODE:=auto}"
: "${CONFIRM_RESIZE:=false}"
# 传入的 instance_id 来自 CMDB / Terraform state, 主机若被重建过, state 里
# 记的就是旧 ID。有一个可现查的稳定标识时(主机名 / 当前 IP), 用它按事实
# 复核并在必要时自愈, 而不是盲信一个可能陈旧的 ID。二者都可留空。
: "${EXPECTED_HOSTNAME:=}"
: "${EXPECTED_IP:=}"
[[ "$INSTANCE_ID" =~ ^[A-Za-z0-9-]{1,128}$ && "$TARGET_PLAN" =~ ^[A-Za-z0-9-]{1,128}$ ]] || exit 2

# GET /v2/instances/{id} 的错误码是可判别的: 无效/空 token -> 401,
# token 有效但该账户下无此 ID -> 404。据此把"凭据问题"和"ID 陈旧"分开,
# 而不是像 curl -f 那样把两者都压成一个 exit 22。
vultr_get_instance() {
  local id="$1" body="$2"
  curl -sS --max-time 30 --retry 3 -o "${body}" -w '%{http_code}' \
    -H "Authorization: Bearer ${VULTR_API_KEY}" \
    "https://api.vultr.com/v2/instances/${id}"
}

# 按主机名或当前 IP 在账户实例列表里现查真实 ID。主机重建后 IP 常保留
# (Vultr 重装/重建同一 reserved IP), 主机名则由我们自己的命名约定保证稳定。
resolve_instance_id() {
  local list; list="$(curl -sS --max-time 30 --retry 3 \
    -H "Authorization: Bearer ${VULTR_API_KEY}" \
    'https://api.vultr.com/v2/instances?per_page=500')" || return 1
  local id=""
  if [[ -n "${EXPECTED_IP}" ]]; then
    id="$(jq -er --arg ip "${EXPECTED_IP}" \
      '[.instances[]? | select(.main_ip == $ip) | .id] | unique | select(length == 1) | .[0]' <<<"${list}")" || return 1
  fi
  if [[ -z "${id}" && -n "${EXPECTED_HOSTNAME}" ]]; then
    id="$(jq -er --arg h "${EXPECTED_HOSTNAME}" \
      '[.instances[]? | select(.label == $h) | .id] | unique | select(length == 1) | .[0]' <<<"${list}")" || return 1
  fi
  printf '%s' "${id}"
}

http_body="$(mktemp)"
trap 'rm -f "${http_body}"' EXIT
http_code="$(vultr_get_instance "${INSTANCE_ID}" "${http_body}")"

case "${http_code}" in
  200) ;;
  401|403)
    echo "::error::Vultr API rejected the credential (HTTP ${http_code}). The VULTR_API_KEY read from kv/data/CICD/${VAULT_ENV_PATH:-<env>} is invalid or lacks permission. This is a credential problem, not a missing instance." >&2
    exit 1 ;;
  404)
    # token 有效(否则会是 401), 但账户里没有这个 ID —— 传入的 instance_id
    # 陈旧, 几乎总是因为主机被重建换了 ID 而 state 没更新。用稳定标识现查。
    echo "::warning::Instance ${INSTANCE_ID} not found (HTTP 404) although the credential is valid. The ID from CMDB/state is stale; re-resolving by hostname/IP." >&2
    resolved="$(resolve_instance_id)"
    if [[ -z "${resolved}" ]]; then
      echo "::error::Could not re-resolve the instance by hostname='${EXPECTED_HOSTNAME:-<unset>}' or ip='${EXPECTED_IP:-<unset>}'. Pass resize_target_domain (label) or the current IP so preflight can find the rebuilt instance, or refresh Terraform state so CMDB carries the current instance_id." >&2
      exit 1
    fi
    echo "::notice::Re-resolved instance ${INSTANCE_ID} -> ${resolved}." >&2
    INSTANCE_ID="${resolved}"
    http_code="$(vultr_get_instance "${INSTANCE_ID}" "${http_body}")"
    [[ "${http_code}" == "200" ]] || {
      echo "::error::Re-resolved instance ${INSTANCE_ID} still returned HTTP ${http_code}." >&2
      exit 1
    } ;;
  *)
    echo "::error::Vultr API returned unexpected HTTP ${http_code} for instance ${INSTANCE_ID}." >&2
    head -c 400 "${http_body}" >&2; exit 1 ;;
esac

instance="$(jq -c '.instance' < "${http_body}")"
current_plan="$(jq -r '.plan // empty' <<<"${instance}")"
region="$(jq -r '.region // empty' <<<"${instance}")"
os_id="$(jq -r '.os_id // empty' <<<"${instance}")"
current_ip="$(jq -r '.main_ip // empty' <<<"${instance}")"
label="$(jq -r '.label // empty' <<<"${instance}")"
source_vcpu="$(jq -r '.vcpu_count // empty' <<<"${instance}")"
source_ram="$(jq -r '.ram // empty' <<<"${instance}")"
source_disk="$(jq -r '.disk // empty' <<<"${instance}")"

[[ -n "${current_plan}" && -n "${region}" && -n "${current_ip}" && -n "${source_vcpu}" && -n "${source_ram}" && -n "${source_disk}" ]] || {
  echo "::error::Vultr instance response is missing plan, region, main_ip, or capacity values" >&2
  exit 1
}

plans="$(curl -fsS --retry 3 -H "Authorization: Bearer ${VULTR_API_KEY}" \
  'https://api.vultr.com/v2/plans?type=vc2&per_page=500')"
target_spec="$(jq -c --arg plan "${TARGET_PLAN}" '.plans[]? | select(.id == $plan)' <<<"${plans}" | head -n 1)"
[[ -n "${target_spec}" ]] || {
  echo "::error::Vultr did not return capacity metadata for target plan ${TARGET_PLAN}" >&2
  exit 1
}
target_vcpu="$(jq -r '.vcpu_count // empty' <<<"${target_spec}")"
target_ram="$(jq -r '.ram // empty' <<<"${target_spec}")"
target_disk="$(jq -r '.disk // empty' <<<"${target_spec}")"
[[ -n "${target_vcpu}" && -n "${target_ram}" && -n "${target_disk}" ]] || {
  echo "::error::Target plan ${TARGET_PLAN} is missing capacity metadata" >&2
  exit 1
}

if [[ "${TARGET_PLAN}" == "${current_plan}" ]]; then
  direction=same
elif (( target_vcpu >= source_vcpu && target_ram >= source_ram && target_disk >= source_disk )); then
  direction=upgrade
else
  direction=downgrade
fi

if [[ "${RESIZE_MODE}" != auto && "${RESIZE_MODE}" != "${direction}" ]]; then
  echo "::error::resize_mode=${RESIZE_MODE} does not match detected direction=${direction}" >&2
  exit 1
fi

if [[ "${direction}" == downgrade && "${CONFIRM_RESIZE}" != true ]]; then
  echo "::error::Downgrade requires confirm_resize=true and the replacement flow." >&2
  exit 1
fi

if [[ "${direction}" == downgrade ]] && (( target_disk < source_disk )); then
  echo "::error::Snapshot replacement is impossible: source disk=${source_disk}GB, target plan ${TARGET_PLAN} disk=${target_disk}GB. Select a plan with at least ${source_disk}GB disk, or use an application-level backup/restore migration." >&2
  exit 1
fi

operation_id="resize-${INSTANCE_ID:0:8}-$(date -u +%Y%m%d%H%M%S)"
{
  echo "instance_id=${INSTANCE_ID}"
  echo "direction=${direction}"
  echo "current_plan=${current_plan}"
  echo "region=${region}"
  echo "os_id=${os_id}"
  echo "current_ip=${current_ip}"
  echo "label=${label}"
  echo "source_disk=${source_disk}"
  echo "target_disk=${target_disk}"
  echo "operation_id=${operation_id}"
} >> "${GITHUB_OUTPUT:-/dev/stdout}"

echo "Resize preflight: ${current_plan} -> ${TARGET_PLAN} (${direction})"
