#!/usr/bin/env bash
set -euo pipefail

# This is intentionally a separate reconciler from the disaster-recovery DNS
# cutover. It remains UAT-only and applies only the canonical records declared
# by the selected GitOps EdgeRoutingConfig.
readonly CLOUDFLARE_API_BASE="${CLOUDFLARE_API_BASE_OVERRIDE:-https://api.cloudflare.com/client/v4}"

: "${CLOUDFLARE_DNS_API_TOKEN:?CLOUDFLARE_DNS_API_TOKEN is required}"
: "${GITOPS_ROUTING_CONFIG:?GITOPS_ROUTING_CONFIG must point to the rendered GitOps manifest}"
if [[ "${DEPLOY_ENV:-}" != "uat" ]]; then
  echo "::error::UAT DNS reconciler requires DEPLOY_ENV=uat." >&2
  exit 1
fi
if [[ -z "${TARGET_DOMAIN_BASE:-}" || "${TARGET_DOMAIN_BASE}" == "${SOURCE_DOMAIN_BASE:-}" || "${TARGET_DOMAIN_BASE}" == *[!a-zA-Z0-9.-]* ]]; then
  echo "::error::UAT DNS reconciler requires a valid target zone distinct from the source zone." >&2
  exit 1
fi
readonly UAT_ZONE="${TARGET_DOMAIN_BASE}"
agent_proxy_only=false
if [[ "${TARGET_DOMAINS:-}" == "agent-proxy" ]]; then
  agent_proxy_only=true
fi

command -v curl >/dev/null || { echo "::error::curl is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "::error::jq is required" >&2; exit 1; }

if [[ ! -f "${GITOPS_ROUTING_CONFIG}" ]]; then
  echo "::error::GitOps routing manifest not found: ${GITOPS_ROUTING_CONFIG}" >&2
  exit 1
fi

if [[ "$(jq -r '.kind // empty' "${GITOPS_ROUTING_CONFIG}")" != "EdgeRoutingConfig" ||
      "$(jq -r '.metadata.mode // empty' "${GITOPS_ROUTING_CONFIG}")" != "selfhost" ||
      "$(jq -r '.spec.runtime.mode // empty' "${GITOPS_ROUTING_CONFIG}")" != "selfhost" ]]; then
  echo "::error::UAT DNS requires a GitOps EdgeRoutingConfig with runtime.mode=selfhost." >&2
  exit 1
fi

config_zone="$(jq -er '.spec.cloudflare.zone_name // empty' "${GITOPS_ROUTING_CONFIG}")"
if [[ "${config_zone}" != "${UAT_ZONE}" ]]; then
  echo "::error::GitOps zone ${config_zone} does not match TARGET_DOMAIN_BASE=${UAT_ZONE}." >&2
  exit 1
fi

dns_control_plane="$(jq -er '.spec.runtime.routing.dns.control_plane // empty' "${GITOPS_ROUTING_CONFIG}")"
dns_ttl="$(jq -er '.spec.runtime.routing.dns.ttl_seconds // empty' "${GITOPS_ROUTING_CONFIG}")"
dns_strategy="$(jq -er '.spec.runtime.routing."load-balancer".strategy // empty' "${GITOPS_ROUTING_CONFIG}")"
selfhost_weight="$(jq -er '.spec.runtime.routing.weight.selfhost // empty' "${GITOPS_ROUTING_CONFIG}")"
serverless_weight="$(jq -er '.spec.runtime.routing.weight.serverless // empty' "${GITOPS_ROUTING_CONFIG}")"
canonical_count="$(jq -er '.spec.runtime.routing.dns.canonical_records | length' "${GITOPS_ROUTING_CONFIG}")"
if [[ "${dns_control_plane}" != "cloudflare-dns" || "${dns_ttl}" != "60" ||
      "${dns_strategy}" != "dns-only" || "${selfhost_weight}" != "100" ||
      "${serverless_weight}" != "0" || "${canonical_count}" != "2" ]]; then
  echo "::error::GitOps selfhost DNS contract must be Cloudflare DNS, ttl=60, dns-only, selfhost=100/serverless=0, with two canonical records." >&2
  exit 1
fi

# Web SaaS is a single full-stack host (control plane, frontend, backend and
# database). These mode-qualified public endpoints must always point at that
# host; the separate agent-proxy node is published below from the agent_proxy CMDB group.
expected_console_name="console-${DEPLOY_ENV}.${UAT_ZONE}"
expected_accounts_name="accounts-${DEPLOY_ENV}.${UAT_ZONE}"
expected_console_target="console-selfhost-${DEPLOY_ENV}.${UAT_ZONE}"
expected_accounts_target="accounts-selfhost-${DEPLOY_ENV}.${UAT_ZONE}"
expected_console_selfhost_name="console-selfhost-${DEPLOY_ENV}.${UAT_ZONE}"
expected_accounts_selfhost_name="accounts-selfhost-${DEPLOY_ENV}.${UAT_ZONE}"
expected_billing_name="billing-selfhost-${DEPLOY_ENV}.${UAT_ZONE}"
expected_postgresql_name="postgresql-selfhost-${DEPLOY_ENV}.${UAT_ZONE}"
expected_bridge_name="bridge-${DEPLOY_ENV}.${UAT_ZONE}"
canonical_records_json="$(jq -c -er '.spec.runtime.routing.dns.canonical_records' "${GITOPS_ROUTING_CONFIG}")"
if [[ "${agent_proxy_only}" != true ]]; then
  actual_console_target="$(jq -r --arg name "${expected_console_name}" '.[$name] // empty' <<<"${canonical_records_json}")"
  actual_accounts_target="$(jq -r --arg name "${expected_accounts_name}" '.[$name] // empty' <<<"${canonical_records_json}")"
  if [[ "${actual_console_target}" != "${expected_console_target}" ||
        "${actual_accounts_target}" != "${expected_accounts_target}" ]]; then
    echo "::error::UAT DNS contract must map ${expected_console_name} -> ${expected_console_target} and ${expected_accounts_name} -> ${expected_accounts_target}." >&2
    exit 1
  fi
fi

cmdb_file="${CMDB_FILE:-cmdb/cmdb.json}"
if [[ ! -f "${cmdb_file}" ]]; then
  echo "::error::CMDB file not found: ${cmdb_file}" >&2
  exit 1
fi

web_saas_ip=""
if [[ "${agent_proxy_only}" != true ]]; then
  mapfile -t web_saas_hosts < <(
    jq -r 'to_entries[] | select(.value | type == "object") | select((.value.groups // []) | index("web_saas")) | .key' "${cmdb_file}"
  )
  if [[ "${#web_saas_hosts[@]}" -ne 1 ]]; then
    echo "::error::UAT DNS requires exactly one web_saas host in ${cmdb_file}; found ${#web_saas_hosts[@]}." >&2
    exit 1
  fi

  web_saas_ip="$(jq -er --arg host "${web_saas_hosts[0]}" '.[$host].ip // empty' "${cmdb_file}")"
  if [[ ! "${web_saas_ip}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || ! jq -n -e --arg ip "${web_saas_ip}" '
    ($ip | split(".")) as $octets
    | ($octets | length == 4)
    and all($octets[]; (tonumber >= 0 and tonumber <= 255))
  ' >/dev/null; then
    echo "::error::CMDB web_saas host has an invalid IPv4 address: ${web_saas_ip}" >&2
    exit 1
  fi
fi

mapfile -t agent_proxy_hosts < <(
  jq -r 'to_entries[] | select(.value | type == "object") | select((.value.groups // []) | index("agent_proxy")) | .key' "${cmdb_file}"
)

agent_proxy_records=()
for agent_proxy_host in "${agent_proxy_hosts[@]}"; do
  agent_proxy_name="$(jq -er --arg host "${agent_proxy_host}" '.[$host].fqdn // $host' "${cmdb_file}")"
  agent_proxy_ip="$(jq -er --arg host "${agent_proxy_host}" '.[$host].ip // empty' "${cmdb_file}")"
  if [[ "${agent_proxy_name}" != *."${UAT_ZONE}" ]]; then
    echo "::error::CMDB agent_proxy host ${agent_proxy_host} must use a ${UAT_ZONE} public FQDN; got ${agent_proxy_name}." >&2
    exit 1
  fi
  if [[ ! "${agent_proxy_ip}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || ! jq -n -e --arg ip "${agent_proxy_ip}" '
    ($ip | split(".")) as $octets
    | ($octets | length == 4)
    and all($octets[]; (tonumber >= 0 and tonumber <= 255))
  ' >/dev/null; then
    echo "::error::CMDB agent_proxy host ${agent_proxy_host} has an invalid IPv4 address: ${agent_proxy_ip}" >&2
    exit 1
  fi
  if [[ "${agent_proxy_ip}" == "${web_saas_ip}" ]]; then
    echo "::error::UAT DNS refuses to reconcile: agent-proxy host ${agent_proxy_host} shares Web SaaS IP ${web_saas_ip}. Fix Terraform state/CMDB before changing DNS." >&2
    exit 1
  fi
  agent_proxy_records+=("${agent_proxy_name}"$'\t'"${agent_proxy_ip}")
done

if [[ "${agent_proxy_only}" == true && "${#agent_proxy_records[@]}" -eq 0 ]]; then
  echo "::error::Agent Proxy-only UAT DNS requires at least one agent_proxy host in ${cmdb_file}." >&2
  exit 1
fi

# Each CMDB node owns its declared regional FQDN. Do not merge regions into a
# single round-robin name: the selected XConnect region must remain stable.
if [[ "${#agent_proxy_records[@]}" -gt 0 ]]; then
  mapfile -t agent_proxy_records < <(printf '%s\n' "${agent_proxy_records[@]}" | sort -u)
fi

api_request() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  local response
  local -a curl_args=(
    --fail-with-body
    --silent
    --show-error
    --retry 2
    --connect-timeout 10
    --max-time 30
    --request "${method}"
    --header "Authorization: Bearer ${CLOUDFLARE_DNS_API_TOKEN}"
    --header "Content-Type: application/json"
  )

  if [[ -n "${body}" ]]; then
    curl_args+=(--data "${body}")
  fi

  if ! response="$(curl "${curl_args[@]}" "${url}")"; then
    echo "::error::Cloudflare API request failed: ${method} ${url}" >&2
    # --fail-with-body already captured Cloudflare's error document on stdout.
    # Dropping it turns every 4xx into a bare URL and an unexplained failure.
    if [[ -n "${response:-}" ]]; then
      echo "Cloudflare API error body:" >&2
      jq -c '.errors // .' <<<"${response}" >&2 || printf '%s\n' "${response}" >&2
    fi
    return 1
  fi
  if ! jq -e '.success == true' >/dev/null <<<"${response}"; then
    echo "::error::Cloudflare API returned success=false: ${method} ${url}" >&2
    jq -c '.errors // .messages // []' <<<"${response}" >&2 || true
    return 1
  fi
  printf '%s' "${response}"
}

delete_record() {
  local zone_id="$1"
  local record_id="$2"
  api_request DELETE "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records/${record_id}" >/dev/null
}

zone_response="$(api_request GET "${CLOUDFLARE_API_BASE}/zones?name=${UAT_ZONE}&status=active")"
zone_id="$(jq -er '
  .result
  | if length == 1 then .[0].id else error("expected exactly one active UAT zone") end
' <<<"${zone_response}")"

desired_payload() {
  local record_name="$1"
  local record_type="$2"
  local record_content="$3"
  local record_ttl="$4"
  jq -cn \
    --arg name "${record_name}" \
    --arg type "${record_type}" \
    --arg content "${record_content}" \
    --argjson ttl "${record_ttl}" \
    '{type:$type, name:$name, content:$content, ttl:$ttl, proxied:false}'
}

reconcile_record() {
  local record_name="$1"
  local record_type="$2"
  local record_content="$3"
  local record_ttl="$4"
  records_response="$(api_request GET "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records?name=${record_name}&per_page=100")"
  primary_id="$(jq -r --arg type "${record_type}" '.result | map(select(.type == $type)) | .[0].id // empty' <<<"${records_response}")"

  if [[ -z "${primary_id}" ]]; then
    while IFS= read -r record_id; do
      [[ -z "${record_id}" ]] || delete_record "${zone_id}" "${record_id}"
    done < <(jq -r '.result[].id' <<<"${records_response}")
    api_request POST "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records" "$(desired_payload "${record_name}" "${record_type}" "${record_content}" "${record_ttl}")" >/dev/null
    echo "Created ${record_name} -> ${record_content} (${record_type})"
    return
  fi

  current_primary="$(jq -c --arg id "${primary_id}" '.result[] | select(.id == $id)' <<<"${records_response}")"
  if ! jq -e --arg name "${record_name}" --arg type "${record_type}" --arg content "${record_content}" --argjson ttl "${record_ttl}" '
    .type == $type
    and .name == $name
    and .content == $content
    and (.ttl | tonumber) == $ttl
    and .proxied == false
  ' >/dev/null <<<"${current_primary}"; then
    api_request PUT "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records/${primary_id}" "$(desired_payload "${record_name}" "${record_type}" "${record_content}" "${record_ttl}")" >/dev/null
    echo "Updated ${record_name} -> ${record_content} (${record_type})"
  else
    echo "Unchanged ${record_name} -> ${record_content} (${record_type})"
  fi

  while IFS= read -r record_id; do
    [[ -z "${record_id}" ]] || delete_record "${zone_id}" "${record_id}"
  done < <(jq -r --arg primary_id "${primary_id}" '.result[] | select(.id != $primary_id) | .id' <<<"${records_response}")
}

reconcile_multi_a_records() {
  local record_name="$1"
  local record_ttl="$2"
  shift 2
  local -a desired_ips=("$@")
  local records_response
  records_response="$(api_request GET "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records?name=${record_name}&per_page=100")"

  declare -A kept_record_ids=()
  for record_content in "${desired_ips[@]}"; do
    primary_id="$(jq -r --arg content "${record_content}" '.result | map(select(.type == "A" and .content == $content)) | .[0].id // empty' <<<"${records_response}")"
    if [[ -z "${primary_id}" ]]; then
      api_request POST "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records" "$(desired_payload "${record_name}" "A" "${record_content}" "${record_ttl}")" >/dev/null
      echo "Created ${record_name} -> ${record_content} (A)"
      continue
    fi

    kept_record_ids["${primary_id}"]=1
    current_primary="$(jq -c --arg id "${primary_id}" '.result[] | select(.id == $id)' <<<"${records_response}")"
    if ! jq -e --arg name "${record_name}" --arg content "${record_content}" --argjson ttl "${record_ttl}" '
      .type == "A"
      and .name == $name
      and .content == $content
      and (.ttl | tonumber) == $ttl
      and .proxied == false
    ' >/dev/null <<<"${current_primary}"; then
      api_request PUT "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records/${primary_id}" "$(desired_payload "${record_name}" "A" "${record_content}" "${record_ttl}")" >/dev/null
      echo "Updated ${record_name} -> ${record_content} (A)"
    else
      echo "Unchanged ${record_name} -> ${record_content} (A)"
    fi
  done

  while IFS= read -r record_id; do
    [[ -z "${record_id}" || -n "${kept_record_ids[${record_id}]+x}" ]] || delete_record "${zone_id}" "${record_id}"
  done < <(jq -r '.result[].id' <<<"${records_response}")
}

# The canonical public entries are owned by the serverless orchestrator, which
# binds them as Worker custom domains when it runs with dns_mode=uat-records.
# Cloudflare refuses to delete a Worker-managed record, so reclaiming them from
# here fails the whole reconciliation on a bare HTTP 400 (run 32219402202) and
# would fight the serverless owner even if it succeeded. Selfhost therefore
# yields any canonical name that already exists and only publishes one that
# nobody owns, so the public entry is never silently left unresolvable.
adopt_or_yield_canonical_record() {
  local record_name="$1"
  local record_target="$2"
  local record_ttl="$3"
  local records_response
  local current_owner
  records_response="$(api_request GET "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records?name=${record_name}&per_page=100")"
  current_owner="$(jq -r '[.result[] | "\(.type) -> \(.content)"] | join(", ")' <<<"${records_response}")"

  if [[ -n "${current_owner}" ]]; then
    echo "Yielded ${record_name}; held by the current owner (${current_owner}). Selfhost does not reclaim canonical public entries."
    return
  fi

  api_request POST "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records" "$(desired_payload "${record_name}" CNAME "${record_target}" "${record_ttl}")" >/dev/null
  echo "Created ${record_name} -> ${record_target} (CNAME)"
}

if [[ "${agent_proxy_only}" != true ]]; then
  while IFS=$'\t' read -r record_name record_target; do
    [[ -n "${record_name}" && -n "${record_target}" ]] || continue
    adopt_or_yield_canonical_record "${record_name}" "${record_target}" "${dns_ttl}"
  done < <(jq -r '.spec.runtime.routing.dns.canonical_records | to_entries[] | [.key, .value] | @tsv' "${GITOPS_ROUTING_CONFIG}")
fi

# These are the deployment-domain records owned by this Web SaaS full-stack
# deployment. The selected Selfhost route owns the mode-qualified endpoints;
# serverless endpoints are reconciled by the serverless workflow.
if [[ "${agent_proxy_only}" != true ]]; then
  reconcile_record "${expected_console_selfhost_name}" A "${web_saas_ip}" 1
  reconcile_record "${expected_accounts_selfhost_name}" A "${web_saas_ip}" 1
  reconcile_record "${expected_billing_name}" A "${web_saas_ip}" 1
  reconcile_record "${expected_postgresql_name}" A "${web_saas_ip}" 1
  reconcile_record "${expected_bridge_name}" A "${web_saas_ip}" 1
fi

if [[ "${#agent_proxy_records[@]}" -gt 0 ]]; then
  while IFS=$'\t' read -r agent_proxy_name agent_proxy_ip; do
    reconcile_record "${agent_proxy_name}" A "${agent_proxy_ip}" 1
  done < <(printf '%s\n' "${agent_proxy_records[@]}")
fi

record_count="${#agent_proxy_records[@]}"
if [[ "${agent_proxy_only}" != true ]]; then
  record_count=$((canonical_count + 5 + ${#agent_proxy_records[@]}))
fi
agent_proxy_summary=""
if [[ "${#agent_proxy_records[@]}" -gt 0 ]]; then
  agent_proxy_summary="$(printf '%s\n' "${agent_proxy_records[@]}" | tr '\t' '=' | paste -sd ', ' -)"
fi
if [[ "${agent_proxy_only}" == true ]]; then
  echo "UAT DNS reconciliation completed for ${record_count} Agent Proxy records in ${UAT_ZONE}; agent-proxy [${agent_proxy_summary}]."
else
  echo "UAT DNS reconciliation completed for ${record_count} desired records in ${UAT_ZONE}; web-saas ${expected_console_selfhost_name} (${web_saas_ip})${agent_proxy_summary:+, agent-proxy [${agent_proxy_summary}]}; canonical public entries stay with their current owner."
fi
