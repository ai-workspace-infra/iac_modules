#!/usr/bin/env bash
set -euo pipefail

# IaC execution owner migrated from the frozen Toolkit executor.
# Reconcile the Cloudflare target domains declared by the serverless
# EdgeRoutingConfig. Frontend Router owns Console and the core Edge Gateway
# owns Accounts. The core Edge Gateway also owns Billing and proxies it to
# Cloud Run. Cloudflare Origin Rules cannot override Host/SNI on non-Enterprise
# plans, so this workflow must not depend on a zone Ruleset for Billing.
# Canonical Console/Accounts aliases are changed only during an explicit
# serverless cutover. A normal deployment must not take ownership of the
# shared canonical records from selfhost.

CONFIG_FILE="${CLOUDFLARE_BOUNDARY_CONFIG:?CLOUDFLARE_BOUNDARY_CONFIG must point to the rendered GitOps manifest}"
CLOUDFLARE_API_BASE="${CLOUDFLARE_API_BASE_OVERRIDE:-https://api.cloudflare.com/client/v4}"
serverless_dns_mode="${SERVERLESS_DNS_MODE:-none}"

case "${serverless_dns_mode}" in
  none|uat-records|prod-cutover)
    ;;
  *)
    echo "SERVERLESS_DNS_MODE must be one of: none, uat-records, prod-cutover" >&2
    exit 2
    ;;
esac

: "${CLOUDFLARE_ACCOUNT_ID:?CLOUDFLARE_ACCOUNT_ID is required}"
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN is required}"

command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "jq is required" >&2; exit 1; }
test -f "${CONFIG_FILE}" || { echo "GitOps routing manifest not found: ${CONFIG_FILE}" >&2; exit 1; }

jq -e '
  .kind == "EdgeRoutingConfig"
  and .metadata.mode == "serverless"
  and .spec.runtime.mode == "serverless"
' "${CONFIG_FILE}" >/dev/null || {
  echo "Cloudflare domain reconciliation requires runtime.mode=serverless" >&2
  exit 1
}

zone_name="$(jq -er '.spec.cloudflare.zone_name' "${CONFIG_FILE}")"
pages_project="$(jq -er '.spec.cloudflare.pages_project' "${CONFIG_FILE}")"
static_cdn_url="$(jq -r '.spec.cloudflare.static_cdn_url // empty' "${CONFIG_FILE}")"
static_cdn_host="${static_cdn_url#*://}"
static_cdn_host="${static_cdn_host%%/*}"
console_host="$(jq -er '.spec.serverless.console_host' "${CONFIG_FILE}")"
accounts_host="$(jq -er '.spec.serverless.accounts_host' "${CONFIG_FILE}")"
billing_host="$(jq -er '.spec.serverless.billing_serverless_host // .spec.serverless.billing_host' "${CONFIG_FILE}")"
billing_origin_host="$(jq -r '.spec.serverless.billing_origin_host // empty' "${CONFIG_FILE}")"
billing_upstream="$(jq -er '.spec.serverless.cloud_run.billing_service' "${CONFIG_FILE}")"
frontend_router_worker="$(jq -er '.spec.serverless.frontend_router.worker_name' "${CONFIG_FILE}")"
core_worker="$(jq -er '.spec.serverless.edge_gateway.boundaries[] | select(.id == "core") | .worker_name' "${CONFIG_FILE}")"


# Stable API aliases are owned by the guarded native API reconciler, never by
# the legacy custom-domain publisher below. Keep original Host Routes even
# when dns_mode=none so later deploys cannot undo GTM alias routing.
is_api_alias() {
  jq -e --arg hostname "$1" '.spec.runtime.routing.dns.api_alias_mode == "worker-routes-cname" and .spec.runtime.routing.dns.api_cname_records[$hostname] != null' "${CONFIG_FILE}" >/dev/null
}

api_request() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  local allow_read_only_delete="${4:-false}"
  CLOUDFLARE_READ_ONLY_DELETE=false
  local response
  local -a curl_args=(
    --fail-with-body
    --silent
    --show-error
    --retry 2
    --connect-timeout 10
    --max-time 30
    --request "${method}"
    --header "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}"
    --header "Content-Type: application/json"
  )
  if [[ -n "${body}" ]]; then
    curl_args+=(--data "${body}")
  fi
  if ! response="$(curl "${curl_args[@]}" "${url}")"; then
    if [[ "${method}" == "DELETE" && "${allow_read_only_delete}" == "true" ]] \
      && jq -e 'any(.errors[]?; .code == 1043 or .code == 1046)' <<<"${response:-}" >/dev/null 2>&1; then
      CLOUDFLARE_READ_ONLY_DELETE=true
      echo "Cloudflare DNS record is provider-managed and not editable by this workflow; leaving it in place: ${url}" >&2
      return 0
    fi
    echo "Cloudflare API request failed: ${method} ${url}" >&2
    if [[ -n "${response:-}" ]]; then
      echo "Cloudflare API error body:" >&2
      jq -c '.' <<<"${response}" >&2 || printf '%s\n' "${response}" >&2
    fi
    return 1
  fi
  if ! jq -e '.success == true' >/dev/null <<<"${response}"; then
    if [[ "${method}" == "DELETE" && "${allow_read_only_delete}" == "true" ]] \
      && jq -e 'any(.errors[]?; .code == 1043 or .code == 1046)' <<<"${response}" >/dev/null 2>&1; then
      CLOUDFLARE_READ_ONLY_DELETE=true
      echo "Cloudflare DNS record is provider-managed and not editable by this workflow; leaving it in place: ${url}" >&2
      return 0
    fi
    echo "Cloudflare API returned success=false: ${method} ${url}" >&2
    jq -c '.errors // .messages // []' <<<"${response}" >&2 || true
    return 1
  fi
  printf '%s' "${response}"
}

resolve_zone_id() {
  local requested_zone="$1"
  local query="name=${requested_zone}&status=active&account.id=${CLOUDFLARE_ACCOUNT_ID}&per_page=100"
  local response
  local candidate_count
  local public_nameservers
  local selected_id

  response="$(api_request GET "${CLOUDFLARE_API_BASE}/zones?${query}")"
  candidate_count="$(jq '.result | length' <<<"${response}")"
  if [[ "${candidate_count}" == "1" ]]; then
    jq -er '.result[0].id' <<<"${response}"
    return
  fi

  # Cloudflare can retain more than one active zone record with the same name
  # in an account. The authoritative nameservers identify which zone actually
  # serves the hostname; never select an arbitrary candidate for a write.
  if ! command -v dig >/dev/null 2>&1; then
    echo "Cannot disambiguate active Cloudflare zones for ${requested_zone}: dig is required" >&2
    return 1
  fi
  public_nameservers="$(dig +short NS "${requested_zone}" | sed 's/[.]$//' | awk 'NF' | sort -u)"
  if [[ -z "${public_nameservers}" ]]; then
    echo "Cannot disambiguate active Cloudflare zones for ${requested_zone}: authoritative nameservers not found" >&2
    return 1
  fi

  selected_id="$(jq -r --arg nameservers "${public_nameservers}" '
    ($nameservers | split("\\n") | map(ascii_downcase)) as $public
    | [.result[]
       | select(any(.name_servers[]?;
           . as $nameserver
           | ($public | index(($nameserver | ascii_downcase | rtrimstr(".")))) != null
         ))
       | .id]
    | unique
    | if length == 1 then .[0] else empty end
  ' <<<"${response}")"
  if [[ -n "${selected_id}" ]]; then
    printf '%s' "${selected_id}"
    return
  fi

  echo "Expected exactly one authoritative active Cloudflare zone for ${requested_zone}; candidates=${candidate_count}, nameservers=${public_nameservers}" >&2
  return 1
}

zone_id="$(resolve_zone_id "${zone_name}")"

zone_id_for_hostname() {
  local hostname="$1"
  local requested_zone
  requested_zone="$(jq -r --arg hostname "${hostname}" '
    .spec.serverless.frontend_router.website // {} |
    if ((.hosts // []) | index($hostname)) != null then .zone_name else empty end
  ' "${CONFIG_FILE}")"
  requested_zone="${requested_zone:-${hostname#*.}}"
  if [[ "${requested_zone}" == "${zone_name}" ]]; then
    printf '%s' "${zone_id}"
    return
  fi
  resolve_zone_id "${requested_zone}"
}

ensure_pages_custom_domain() {
  local hostname="$1"
  [[ -n "${hostname}" && "${hostname}" != *.pages.dev ]] || return 0
  local domains_url="${CLOUDFLARE_API_BASE}/accounts/${CLOUDFLARE_ACCOUNT_ID}/pages/projects/${pages_project}/domains"
  local domains_response
  local existing_status
  local body
  domains_response="$(api_request GET "${domains_url}")"
  existing_status="$(jq -r --arg hostname "${hostname}" 'first(.result[]? | select(.name == $hostname) | .status) // empty' <<<"${domains_response}")"
  if [[ -n "${existing_status}" ]]; then
    echo "Pages custom domain present: ${hostname} (status=${existing_status})"
    return 0
  fi
  body="$(jq -cn --arg name "${hostname}" '{name: $name}')"
  api_request POST "${domains_url}" "${body}" >/dev/null
  echo "Pages custom domain attached: ${hostname} -> ${pages_project}"
}

safeguard_pages_domain() {
  local hostname="$1"
  local domains_url="${CLOUDFLARE_API_BASE}/accounts/${CLOUDFLARE_ACCOUNT_ID}/pages/projects/${pages_project}/domains"
  local domains_response
  local existing_name
  local existing_status
  domains_response="$(api_request GET "${domains_url}" || echo '{"result":[]}')"
  existing_name="$(jq -r --arg hostname "${hostname}" 'first(.result[]? | select(.name == $hostname) | .name) // empty' <<<"${domains_response}")"
  existing_status="$(jq -r --arg hostname "${hostname}" 'first(.result[]? | select(.name == $hostname) | .status // "unknown")' <<<"${domains_response}")"

  if [[ -n "${existing_name}" ]]; then
    echo "Detaching stale Pages domain (${existing_name}, status=${existing_status}) to allow Worker custom domain binding..."
    api_request DELETE "${domains_url}/${existing_name}" >/dev/null || true
  fi
  echo "Pages does not own the Worker Console target: ${hostname}"
}

reconcile_worker_domain() {
  local hostname="$1"
  local service="$2"
  local domains_url="${CLOUDFLARE_API_BASE}/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/domains?per_page=100"
  local domains_response
  local existing
  local conflicting_service
  local body
  local target_zone_name
  target_zone_name="$(jq -r --arg hostname "${hostname}" '
    .spec.serverless.frontend_router.website // {} |
    if ((.hosts // []) | index($hostname)) != null then .zone_name else empty end
  ' "${CONFIG_FILE}")"
  target_zone_name="${target_zone_name:-${hostname#*.}}"
  local target_zone_id
  target_zone_id="$(zone_id_for_hostname "${hostname}")"
  domains_response="$(api_request GET "${domains_url}")"
  existing="$(jq -r --arg hostname "${hostname}" --arg service "${service}" '
    first(.result[]? | select(.hostname == $hostname and .service == $service) | [.hostname, .service] | @tsv) // empty
  ' <<<"${domains_response}")"
  if [[ -n "${existing}" ]]; then
    echo "Worker custom domain present: ${existing}"
    return
  fi
  conflicting_service="$(jq -r --arg hostname "${hostname}" '
    first(.result[]? | select(.hostname == $hostname) | .service) // empty
  ' <<<"${domains_response}")"
  if [[ -n "${conflicting_service}" ]]; then
    echo "Worker custom domain ${hostname} is already owned by ${conflicting_service}, not ${service}. Resolve the ownership explicitly before rerunning." >&2
    return 1
  fi

  body="$(jq -cn \
    --arg hostname "${hostname}" \
    --arg service "${service}" \
    --arg zone_id "${target_zone_id}" \
    --arg zone_name "${target_zone_name}" \
    '{hostname: $hostname, service: $service, zone_id: $zone_id, zone_name: $zone_name}')"
  api_request PUT "${CLOUDFLARE_API_BASE}/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/domains" "${body}" >/dev/null
  echo "Worker custom domain attached: ${hostname} -> ${service}"
}

remove_worker_routes_for_host() {
  local hostname="$1"
  local expected_service="${2:-}"
  local routes_zone_id
  routes_zone_id="$(zone_id_for_hostname "${hostname}")"
  local routes_url="${CLOUDFLARE_API_BASE}/zones/${routes_zone_id}/workers/routes"
  local routes_response
  local route_id
  local pattern
  local pattern_host
  local route_service

  routes_response="$(api_request GET "${routes_url}")"
  while IFS=$'\t' read -r route_id pattern route_service; do
    [[ -n "${route_id}" && -n "${pattern}" ]] || continue
    pattern_host="${pattern#*://}"
    pattern_host="${pattern_host%%/*}"
    pattern_host="${pattern_host%%:*}"
    if [[ "${pattern_host}" != "${hostname}" ]]; then
      continue
    fi
    if [[ -n "${expected_service}" && "${route_service}" != "${expected_service}" ]]; then
      continue
    fi
    api_request DELETE "${routes_url}/${route_id}" >/dev/null
    echo "Removed stale Worker Route: ${pattern}"
  done < <(jq -r '.result[]? | [.id, .pattern, (.script // empty)] | @tsv' <<<"${routes_response}")
}

detach_worker_domain() {
  local hostname="$1"
  local expected_service="$2"
  local domains_url="${CLOUDFLARE_API_BASE}/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/domains?per_page=100"
  local domains_response
  local refreshed_domains_response
  domains_response="$(api_request GET "${domains_url}")"

  while IFS=$'\t' read -r domain_id domain_service; do
    [[ -n "${domain_id}" ]] || continue
    if [[ "${domain_service}" != "${expected_service}" ]]; then
      echo "Worker custom domain ${hostname} is owned by ${domain_service}, not ${expected_service}; refusing to detach it." >&2
      return 1
    fi
    # Cloudflare custom-domain deletion is eventually consistent. A concurrent
    # deploy can remove the same stale binding after our list request but
    # before this DELETE; treat that specific already-absent outcome as
    # success only after a fresh authoritative read. Do not hide a permission
    # or ownership failure when the binding is still present.
    if ! api_request DELETE "${CLOUDFLARE_API_BASE}/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/domains/${domain_id}" >/dev/null; then
      refreshed_domains_response="$(api_request GET "${domains_url}")" || return 1
      if jq -e --arg hostname "${hostname}" --arg domain_id "${domain_id}" '
        any(.result[]?; .hostname == $hostname and .id == $domain_id)
      ' <<<"${refreshed_domains_response}" >/dev/null; then
        echo "Worker custom domain ${hostname} remains after its delete request; refusing to continue." >&2
        return 1
      fi
      echo "Worker custom domain already detached concurrently: ${hostname} -> ${domain_service}"
      continue
    fi
    echo "Detached Worker custom domain: ${hostname} -> ${domain_service}"
  done < <(jq -r --arg hostname "${hostname}" '.result[]? | select(.hostname == $hostname) | [.id, .service] | @tsv' <<<"${domains_response}")
}

remove_declared_cname() {
  local name="$1"
  shift
  local -a allowed_targets=("$@")
  local records_response
  local expected_target
  local target_allowed
  records_response="$(api_request GET "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records?name=${name}&type=CNAME&per_page=100")"

  while IFS=$'\t' read -r record_id record_target; do
    [[ -n "${record_id}" ]] || continue
    if ((${#allowed_targets[@]} > 0)); then
      target_allowed=false
      for expected_target in "${allowed_targets[@]}"; do
        if [[ -n "${expected_target}" && "${record_target%.}" == "${expected_target%.}" ]]; then
          target_allowed=true
          break
        fi
      done
      if [[ "${target_allowed}" != true ]]; then
        echo "DNS CNAME ${name} points to unexpected target ${record_target}; refusing to delete it." >&2
        return 1
      fi
    fi
    api_request DELETE "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records/${record_id}" "" true >/dev/null
    if [[ "${CLOUDFLARE_READ_ONLY_DELETE}" == true ]]; then
      echo "Skipped provider-managed DNS CNAME: ${name} -> ${record_target}"
    else
      echo "Removed conflicting DNS CNAME: ${name} -> ${record_target}"
    fi
  done < <(jq -r '.result[]? | [.id, .content] | @tsv' <<<"${records_response}")
}

remove_worker_domain_dns_records() {
  local hostname="$1"
  local records_response
  local record_id
  local record_type
  local record_content
  local hostname_zone_id

  # Worker custom domains cannot coexist with any DNS record for the same
  # hostname. UAT and production cutovers explicitly transfer ownership of
  # the declared Worker hostnames, so remove the conflicting records before
  # asking the Workers API to attach the custom domain.
  [[ "${serverless_dns_mode}" == "uat-records" || "${serverless_dns_mode}" == "prod-cutover" ]] || return 0
  hostname_zone_id="$(zone_id_for_hostname "${hostname}")"
  records_response="$(api_request GET "${CLOUDFLARE_API_BASE}/zones/${hostname_zone_id}/dns_records?name=${hostname}&per_page=100")"
  while IFS=$'\t' read -r record_id record_type record_content; do
    [[ -n "${record_id}" ]] || continue
    api_request DELETE "${CLOUDFLARE_API_BASE}/zones/${hostname_zone_id}/dns_records/${record_id}" "" true >/dev/null
    if [[ "${CLOUDFLARE_READ_ONLY_DELETE}" == true ]]; then
      echo "Skipped provider-managed DNS record: ${hostname} (${record_type} -> ${record_content})"
    else
      echo "Removed DNS record for Worker custom domain: ${hostname} (${record_type} -> ${record_content})"
    fi
  done < <(jq -r '.result[]? | [.id, .type, .content] | @tsv' <<<"${records_response}")
}

reconcile_cname_record() {
  local name="$1"
  local target="$2"
  local proxied="${3:-true}"
  local records_response
  local primary_id
  records_response="$(api_request GET "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records?name=${name}&type=CNAME&per_page=10")"
  primary_id="$(jq -r '.result[0].id // empty' <<<"${records_response}")"
  local body
  # Public entries stay proxied; the Billing origin alias must remain DNS-only
  # so the Origin Rule cannot recurse through Cloudflare.
  body="$(jq -cn --arg name "${name}" --arg target "${target}" --argjson proxied "${proxied}" '{type:"CNAME", name:$name, content:$target, ttl:60, proxied:$proxied}')"
  if [[ -z "${primary_id}" ]]; then
    api_request POST "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records" "${body}" >/dev/null
    echo "Created DNS CNAME: ${name} -> ${target}"
  else
    api_request PUT "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records/${primary_id}" "${body}" >/dev/null
    echo "Updated DNS CNAME: ${name} -> ${target}"
  fi
}

remove_address_records() {
  local name="$1"
  local records_response
  local record_id
  local record_type
  local record_target
  records_response="$(api_request GET "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records?name=${name}&per_page=100")"
  while IFS=$'\t' read -r record_id record_type record_target; do
    [[ -n "${record_id}" ]] || continue
    case "${record_type}" in
      A|AAAA|CNAME)
        api_request DELETE "${CLOUDFLARE_API_BASE}/zones/${zone_id}/dns_records/${record_id}" "" true >/dev/null
        if [[ "${CLOUDFLARE_READ_ONLY_DELETE}" == true ]]; then
          echo "Skipped provider-managed DNS ${record_type}: ${name} -> ${record_target}"
        else
          echo "Removed conflicting DNS ${record_type}: ${name} -> ${record_target}"
        fi
        ;;
    esac
  done < <(jq -r '.result[]? | [.id, .type, (.content // "")] | @tsv' <<<"${records_response}")
}

if [[ -n "${static_cdn_host}" && "${static_cdn_host}" != *.pages.dev ]]; then
  ensure_pages_custom_domain "${static_cdn_host}"
  reconcile_cname_record "${static_cdn_host}" "${pages_project}.pages.dev"
fi
safeguard_pages_domain "${console_host}"
while IFS= read -r console_alias; do
  [[ -n "${console_alias}" ]] || continue
  safeguard_pages_domain "${console_alias}"
done < <(jq -r '(.spec.serverless.console_aliases // []) + (.spec.serverless.frontend_router.website.hosts // []) | unique[]' "${CONFIG_FILE}")
remove_worker_domain_dns_records "${console_host}"
reconcile_worker_domain "${console_host}" "${frontend_router_worker}"
while IFS= read -r console_alias; do
  [[ -n "${console_alias}" ]] || continue
  remove_worker_domain_dns_records "${console_alias}"
  reconcile_worker_domain "${console_alias}" "${frontend_router_worker}"
done < <(jq -r '(.spec.serverless.console_aliases // []) + (.spec.serverless.frontend_router.website.hosts // []) | unique[]' "${CONFIG_FILE}")
# A Worker custom domain is the only supported owner for Console. Explicit
# Worker Routes take precedence over it and can bypass Frontend Router, so
# remove every route on the GitOps-declared Console host.
remove_worker_routes_for_host "${console_host}"
while IFS= read -r console_alias; do
  [[ -n "${console_alias}" ]] || continue
  remove_worker_routes_for_host "${console_alias}"
done < <(jq -r '(.spec.serverless.console_aliases // []) + (.spec.serverless.frontend_router.website.hosts // []) | unique[]' "${CONFIG_FILE}")
reconcile_worker_domain "${accounts_host}" "${core_worker}"
while IFS= read -r accounts_alias; do
  [[ -n "${accounts_alias}" ]] || continue
  if is_api_alias "${accounts_alias}"; then continue; fi
  remove_worker_domain_dns_records "${accounts_alias}"
  reconcile_worker_domain "${accounts_alias}" "${core_worker}"
done < <(jq -r '.spec.serverless.accounts_aliases[]? // empty' "${CONFIG_FILE}")
remove_worker_domain_dns_records "${billing_host}"
remove_declared_cname "${billing_host}" "${billing_upstream#https://}"
reconcile_worker_domain "${billing_host}" "${core_worker}"
# Remove the DNS-only alias left by the retired Enterprise-only Origin Rule
# design. It is not part of the public service contract.
if [[ -n "${billing_origin_host}" ]]; then
  remove_declared_cname "${billing_origin_host}" "${billing_upstream#https://}"
fi

if [[ "${serverless_dns_mode}" != "none" ]]; then
  while IFS=$'\t' read -r record_name record_target; do
    [[ -n "${record_name}" && -n "${record_target}" ]] || continue
    if is_api_alias "${record_name}"; then continue; fi
    # A canonical hostname must be the Worker custom domain itself. Pointing a
    # proxied CNAME at another Worker custom domain makes the target an origin
    # and can produce a 522/self-fetch loop. Cloudflare creates the DNS record
    # for the custom domain after the old record is removed.
    if [[ "${record_target%.}" == "${accounts_host%.}" ]]; then
      expected_worker="${core_worker}"
    else
      expected_worker="${frontend_router_worker}"
    fi
    remove_address_records "${record_name}"
    reconcile_worker_domain "${record_name}" "${expected_worker}"
  done < <(jq -r '.spec.runtime.routing.dns.canonical_records // {} | to_entries[] | [.key, .value] | @tsv' "${CONFIG_FILE}")
else
  while IFS=$'\t' read -r record_name record_target; do
    [[ "${record_target%.}" == "${accounts_host%.}" ]] || continue
    if is_api_alias "${record_name}"; then continue; fi
    # Edge Gateway deployment may declare canonical API routes for explicit
    # cutovers. A normal dns_mode=none run must remove only its own legacy
    # route and leave unrelated scripts untouched.
    remove_worker_routes_for_host "${record_name}" "${core_worker}"
  done < <(jq -r '.spec.runtime.routing.dns.canonical_records // {} | to_entries[] | [.key, .value] | @tsv' "${CONFIG_FILE}")
  echo "Skipping canonical DNS reconciliation; SERVERLESS_DNS_MODE=none leaves shared records under the current owner."
fi

echo "Cloudflare serverless mode domains and DNS reconciled for ${zone_name} (dns_mode=${serverless_dns_mode})."
