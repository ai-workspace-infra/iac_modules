#!/usr/bin/env bash
set -euo pipefail

# SIT deliberately collapses the stack onto one host. Keep this reconciler
# separate from the UAT/production-shaped route so a SIT CMDB can share one IP
# across Web SaaS and Agent Proxy without weakening the UAT safety boundary.
readonly CLOUDFLARE_API_BASE="${CLOUDFLARE_API_BASE_OVERRIDE:-https://api.cloudflare.com/client/v4}"

: "${CLOUDFLARE_DNS_API_TOKEN:?CLOUDFLARE_DNS_API_TOKEN is required}"
: "${CMDB_FILE:?CMDB_FILE must point to the rendered SIT CMDB}"
if [[ "${DEPLOY_ENV:-}" != "sit" ]]; then
  echo "::error::SIT all-in-one DNS reconciler requires DEPLOY_ENV=sit." >&2
  exit 1
fi
if [[ -z "${TARGET_DOMAIN_BASE:-}" || "${TARGET_DOMAIN_BASE}" == "${SOURCE_DOMAIN_BASE:-}" || "${TARGET_DOMAIN_BASE}" == *[!a-zA-Z0-9.-]* ]]; then
  echo "::error::SIT DNS reconciler requires a valid target zone distinct from the source zone." >&2
  exit 1
fi
if [[ ! -f "${CMDB_FILE}" ]]; then
  echo "::error::CMDB file not found: ${CMDB_FILE}" >&2
  exit 1
fi

command -v curl >/dev/null || { echo "::error::curl is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "::error::jq is required" >&2; exit 1; }

mapfile -t all_in_one_hosts < <(
  jq -r 'to_entries[] | select((.value.groups // []) | index("all_in_one")) | .key' "${CMDB_FILE}"
)
if [[ "${#all_in_one_hosts[@]}" -ne 1 ]]; then
  echo "::error::SIT DNS requires exactly one all_in_one host in ${CMDB_FILE}; found ${#all_in_one_hosts[@]}." >&2
  exit 1
fi

all_in_one_ip="$(jq -er --arg host "${all_in_one_hosts[0]}" '.[$host].ip // empty' "${CMDB_FILE}")"
if [[ ! "${all_in_one_ip}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || ! jq -n -e --arg ip "${all_in_one_ip}" '
  ($ip | split(".")) as $octets
  | ($octets | length == 4)
  and all($octets[]; (tonumber >= 0 and tonumber <= 255))
' >/dev/null; then
  echo "::error::CMDB all_in_one host has an invalid IPv4 address: ${all_in_one_ip}" >&2
  exit 1
fi

api_request() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  local response
  local -a curl_args=(
    --fail-with-body --silent --show-error --retry 2
    --connect-timeout 10 --max-time 30
    --request "${method}"
    --header "Authorization: Bearer ${CLOUDFLARE_DNS_API_TOKEN}"
    --header "Content-Type: application/json"
  )
  [[ -z "${body}" ]] || curl_args+=(--data "${body}")
  if ! response="$(curl "${curl_args[@]}" "${url}")"; then
    echo "::error::Cloudflare API request failed: ${method} ${url}" >&2
    return 1
  fi
  if ! jq -e '.success == true' >/dev/null <<<"${response}"; then
    echo "::error::Cloudflare API returned success=false: ${method} ${url}" >&2
    jq -c '.errors // .messages // []' <<<"${response}" >&2 || true
    return 1
  fi
  printf '%s' "${response}"
}

desired_payload() {
  jq -cn \
    --arg name "$1" \
    --arg content "$2" \
    --argjson ttl "$3" \
    '{type:"A", name:$name, content:$content, ttl:$ttl, proxied:false}'
}

delete_record() {
  api_request DELETE "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records/$1" >/dev/null
}

reconcile_record() {
  local record_name="$1"
  local records_response primary_id current_primary record_id
  records_response="$(api_request GET "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records?name=${record_name}&per_page=100")"
  primary_id="$(jq -r '.result | map(select(.type == "A")) | .[0].id // empty' <<<"${records_response}")"

  if [[ -z "${primary_id}" ]]; then
    while IFS= read -r record_id; do
      [[ -z "${record_id}" ]] || delete_record "${record_id}"
    done < <(jq -r '.result[].id' <<<"${records_response}")
    api_request POST "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records" "$(desired_payload "${record_name}" "${all_in_one_ip}" 1)" >/dev/null
    echo "Created ${record_name} -> ${all_in_one_ip} (A)"
    return
  fi

  current_primary="$(jq -c --arg id "${primary_id}" '.result[] | select(.id == $id)' <<<"${records_response}")"
  if ! jq -e --arg name "${record_name}" --arg content "${all_in_one_ip}" '
    .type == "A" and .name == $name and .content == $content
    and (.ttl | tonumber) == 1 and .proxied == false
  ' >/dev/null <<<"${current_primary}"; then
    api_request PUT "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records/${primary_id}" "$(desired_payload "${record_name}" "${all_in_one_ip}" 1)" >/dev/null
    echo "Updated ${record_name} -> ${all_in_one_ip} (A)"
  else
    echo "Unchanged ${record_name} -> ${all_in_one_ip} (A)"
  fi

  while IFS= read -r record_id; do
    [[ -z "${record_id}" || "${record_id}" == "${primary_id}" ]] || delete_record "${record_id}"
  done < <(jq -r '.result[].id' <<<"${records_response}")
}

zone_response="$(api_request GET "${CLOUDFLARE_API_BASE}/zones?name=${TARGET_DOMAIN_BASE}&status=active")"
zone_id="$(jq -er '.result | if length == 1 then .[0].id else error("expected exactly one active SIT zone") end' <<<"${zone_response}")"

for record_name in \
  "console-selfhost-sit.${TARGET_DOMAIN_BASE}" \
  "accounts-selfhost-sit.${TARGET_DOMAIN_BASE}" \
  "billing-selfhost-sit.${TARGET_DOMAIN_BASE}" \
  "postgresql-selfhost-sit.${TARGET_DOMAIN_BASE}" \
  "agent-proxy-selfhost-sit.${TARGET_DOMAIN_BASE}"; do
  reconcile_record "${record_name}"
done

echo "SIT all-in-one DNS reconciliation completed for 5 records in ${TARGET_DOMAIN_BASE}; host ${all_in_one_hosts[0]} (${all_in_one_ip})."
