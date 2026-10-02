#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# 按声明落实每台实例的自动备份计划。
#
# 这一步接手的是 vultr_instance 刻意不再做的事(见 iac_modules
# modules/compute/main.tf 里的说明): provider 在实例创建后立刻设置备份计划,
# Vultr 侧此时常常还没准备好, 返回 404 Invalid instance-id, 于是 Create 失败,
# 但实例已经建出来并写进了 state —— 一条半成品记录, 后续每次 plan 都崩在
# refresh 上。
#
# 放到 apply 之后就没有这个竞态: 实例早已 active, instance_id 是 terraform
# 输出进 CMDB 的事实。这一步先 GET 现状再决定要不要写, 已经一致就一个请求都
# 不发, 因此可以在每次 apply 之后无条件执行, 重复运行结果相同。
#
# Vultr 侧备份是两个动作: PATCH /instances/{id} 开关 backups, POST
# /instances/{id}/backup-schedule 设置计划 —— 与 provider 内部做法一致。
# 关闭只停掉后续计划, 不删除已经生成的备份。
# -----------------------------------------------------------------------------

: "${VULTR_API_KEY:?VULTR_API_KEY is required}"
: "${HOSTS_MANIFEST:=hosts_manifest.json}"
: "${CMDB_FILE:=cmdb.json}"

[[ -f "${HOSTS_MANIFEST}" ]] || {
  echo "::error::${HOSTS_MANIFEST} is missing; run generate.py render first." >&2
  exit 1
}
[[ -f "${CMDB_FILE}" ]] || {
  echo "::error::${CMDB_FILE} is missing; run generate.py inventory after apply first." >&2
  exit 1
}

body="$(mktemp)"
trap 'rm -f "${body}"' EXIT

api() {
  local method="$1" url="$2" payload="${3:-}"
  if [[ -n "${payload}" ]]; then
    curl -sS --retry 3 --retry-connrefused -X "${method}" -o "${body}" -w '%{http_code}' \
      -H "Authorization: Bearer ${VULTR_API_KEY}" \
      -H "Content-Type: application/json" \
      --data "${payload}" "${url}"
  else
    curl -sS --retry 3 --retry-connrefused -X "${method}" -o "${body}" -w '%{http_code}' \
      -H "Authorization: Bearer ${VULTR_API_KEY}" "${url}"
  fi
}

# 401/403 是凭据问题, 任何其它非 2xx 都是未知状态 —— 都不能当作"备份已经就绪"
# 悄悄放过, 否则声明开了备份的数据库主机可能一直没有备份而流水线全绿。
require_ok() {
  local http_code="$1" what="$2"
  case "${http_code}" in
    2*) return 0 ;;
    401|403)
      echo "::error::Vultr API rejected the credential (HTTP ${http_code}) while ${what}." >&2 ;;
    *)
      echo "::error::Vultr API returned HTTP ${http_code} while ${what}." >&2 ;;
  esac
  head -c 400 "${body}" >&2
  exit 1
}

set_backups_flag() {
  local instance_id="$1" name="$2" desired="$3"
  local http_code
  http_code="$(api PATCH "https://api.vultr.com/v2/instances/${instance_id}" \
    "$(jq -nc --arg b "${desired}" '{backups: $b}')")"
  require_ok "${http_code}" "setting backups=${desired} on ${name} (${instance_id})"
}

changed=0
checked=0

# manifest 以主机名(name)为键, CMDB 以 service_domains 首个 FQDN 为键但保留
# name 字段 —— 用 name 关联, 它是两侧共同的声明来源。
while IFS=$'\t' read -r name want_backups want_schedule; do
  instance_id="$(jq -r --arg n "${name}" \
    '[ .[] | select(.name == $n) | .instance_id ] | first // ""' "${CMDB_FILE}")"

  if [[ -z "${instance_id}" || "${instance_id}" == "null" ]]; then
    echo "::error::${name} has no instance_id in ${CMDB_FILE}; apply produced no runtime fact for a host this profile declares." >&2
    exit 1
  fi

  checked=$((checked + 1))
  schedule_url="https://api.vultr.com/v2/instances/${instance_id}/backup-schedule"

  http_code="$(api GET "${schedule_url}")"
  require_ok "${http_code}" "reading the backup schedule of ${name} (${instance_id})"

  current="$(jq -c '.backup_schedule // {}' < "${body}")"
  current_enabled="$(jq -r '.enabled // false' <<<"${current}")"

  if [[ "${want_backups}" != "true" ]]; then
    if [[ "${current_enabled}" == "true" ]]; then
      set_backups_flag "${instance_id}" "${name}" disabled
      echo "  disabled ${name} (${instance_id}): declaration says backups: false"
      changed=$((changed + 1))
    else
      echo "  ok       ${name}: backups already disabled"
    fi
    continue
  fi

  # 只比较声明里实际出现的字段。Vultr 对 daily 计划也会回填 dow/dom, 拿它们跟
  # 未声明的字段比会让每次运行都判成漂移, 于是反复写同一份计划。
  drift="$(jq -n --argjson want "${want_schedule}" --argjson have "${current}" '
    ($have.enabled // false) as $enabled
    | [ $want | to_entries[] | select(.value != null)
        | select(($have[.key] | tostring) != (.value | tostring)) ]
    | (length > 0) or ($enabled | not)
  ')"

  if [[ "${drift}" != "true" ]]; then
    echo "  ok       ${name}: backup schedule already matches the declaration"
    continue
  fi

  if [[ "${current_enabled}" != "true" ]]; then
    set_backups_flag "${instance_id}" "${name}" enabled
  fi

  payload="$(jq -nc --argjson want "${want_schedule}" '$want')"
  http_code="$(api POST "${schedule_url}" "${payload}")"
  require_ok "${http_code}" "setting the backup schedule of ${name} (${instance_id})"

  echo "  set      ${name} (${instance_id}) -> ${payload}"
  changed=$((changed + 1))
done < <(jq -r '.hosts[]? | [.name, (.backups | tostring), (.backups_schedule | tojson)] | @tsv' "${HOSTS_MANIFEST}")

echo "Backup schedule reconcile: ${checked} host(s) checked, ${changed} changed."
