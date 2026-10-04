#!/usr/bin/env bash
set -euo pipefail

# Provider operation for a reviewed resize cutover. Inputs are supplied by the
# control plane; no credentials or DNS state are persisted in this repository.
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN is required}"
: "${CLOUDFLARE_ZONE_ID:?CLOUDFLARE_ZONE_ID is required}"
: "${TARGET_DOMAIN:?TARGET_DOMAIN is required}"
: "${REPLACEMENT_IP:?REPLACEMENT_IP is required}"

record="$(curl -fsS --retry 3 \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  -H 'Content-Type: application/json' \
  "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records?type=A&name=${TARGET_DOMAIN}" \
  | jq -c '.result[0] // empty')"
[[ -n "${record}" ]] || {
  echo "::error::Cloudflare A record not found for ${TARGET_DOMAIN}" >&2
  exit 1
}

record_id="$(jq -r '.id' <<<"${record}")"
payload="$(jq -n --arg name "${TARGET_DOMAIN}" --arg ip "${REPLACEMENT_IP}" \
  '{type:"A",name:$name,content:$ip,ttl:60,proxied:false}')"
curl -fsS --retry 3 -X PUT \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "${payload}" \
  "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${record_id}" \
  | jq -e '.success == true' >/dev/null
