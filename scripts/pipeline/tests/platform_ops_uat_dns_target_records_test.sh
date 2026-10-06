#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
reconciler="${repo_root}/scripts/pipeline/cloudflare-uat-dns-reconcile.sh"
test_dir="$(mktemp -d)"
trap 'rm -rf "${test_dir}"' EXIT

mkdir -p "${test_dir}/bin"
cat >"${test_dir}/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

method="GET"
body=""
url="${!#}"
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --request)
      method="$2"
      shift 2
      ;;
    --data)
      body="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

printf '%s\t%s\t%s\n' "${method}" "${url}" "${body}" >>"${MOCK_CURL_LOG}"
if [[ "${url}" == *'/zones?name='* ]]; then
  printf '%s' '{"success":true,"result":[{"id":"zone-1"}]}'
elif [[ "${method}" == "GET" ]]; then
  printf '%s' '{"success":true,"result":[]}'
else
  printf '%s' '{"success":true,"result":{"id":"record-1"}}'
fi
EOF
chmod +x "${test_dir}/bin/curl"

cat >"${test_dir}/routing.json" <<'EOF'
{
  "kind": "EdgeRoutingConfig",
  "metadata": {"mode": "selfhost"},
  "spec": {
    "runtime": {
      "mode": "selfhost",
      "routing": {
        "dns": {
          "control_plane": "cloudflare-dns",
          "ttl_seconds": 60,
          "canonical_records": {
            "console-uat.onwalk.net": "console-selfhost-uat.onwalk.net",
            "accounts-uat.onwalk.net": "accounts-selfhost-uat.onwalk.net"
          }
        },
        "load-balancer": {"strategy": "dns-only"},
        "weight": {"selfhost": 100, "serverless": 0}
      }
    },
    "cloudflare": {"zone_name": "onwalk.net"}
  }
}
EOF

cat >"${test_dir}/cmdb.json" <<'EOF'
{
  "environment": "uat",
  "project_id": "open-platform-uat",
  "cloud_run_uri": null,
  "declared_spot_vms": ["web-saas-uat"],
  "spot_instances": {},
  "console-uat.onwalk.net": {
    "ip": "192.0.2.138",
    "groups": ["web_saas"]
  },
  "jp-xconnect.onwalk.net": {
    "fqdn": "jp-xconnect.onwalk.net",
    "ip": "167.179.105.137",
    "groups": ["agent_proxy"]
  },
  "us-xconnect.onwalk.net": {
    "fqdn": "us-xconnect.onwalk.net",
    "ip": "167.179.110.129",
    "groups": ["agent_proxy"]
  }
}
EOF

output="$({
  PATH="${test_dir}/bin:${PATH}" \
  MOCK_CURL_LOG="${test_dir}/curl.log" \
  CLOUDFLARE_DNS_API_TOKEN="test-token" \
  CLOUDFLARE_API_BASE_OVERRIDE="https://cloudflare.invalid/client/v4" \
  DEPLOY_ENV="uat" \
  SOURCE_DOMAIN_BASE="svc.plus" \
  TARGET_DOMAIN_BASE="onwalk.net" \
  CMDB_FILE="${test_dir}/cmdb.json" \
  GITOPS_ROUTING_CONFIG="${test_dir}/routing.json" \
  "${reconciler}"
} 2>&1)"

grep -Fq 'Created console-selfhost-uat.onwalk.net -> 192.0.2.138 (A)' <<<"${output}"
grep -Fq 'Created accounts-selfhost-uat.onwalk.net -> 192.0.2.138 (A)' <<<"${output}"
grep -Fq 'Created billing-selfhost-uat.onwalk.net -> 192.0.2.138 (A)' <<<"${output}"
grep -Fq 'Created console-uat.onwalk.net -> console-selfhost-uat.onwalk.net (CNAME)' <<<"${output}"
grep -Fq 'Created accounts-uat.onwalk.net -> accounts-selfhost-uat.onwalk.net (CNAME)' <<<"${output}"
grep -Fq 'Created postgresql-selfhost-uat.onwalk.net -> 192.0.2.138 (A)' <<<"${output}"
grep -Fq 'Created bridge-uat.onwalk.net -> 192.0.2.138 (A)' <<<"${output}"
grep -Fq 'Created jp-xconnect.onwalk.net -> 167.179.105.137 (A)' <<<"${output}"
grep -Fq 'Created us-xconnect.onwalk.net -> 167.179.110.129 (A)' <<<"${output}"
grep -Fq 'completed for 9 desired records' <<<"${output}"

cut -f3 "${test_dir}/curl.log" | jq -s -e \
  'any(.[]; .type == "A" and .name == "console-selfhost-uat.onwalk.net" and .content == "192.0.2.138")' >/dev/null
cut -f3 "${test_dir}/curl.log" | jq -s -e \
  'any(.[]; .type == "A" and .name == "accounts-selfhost-uat.onwalk.net" and .content == "192.0.2.138")' >/dev/null
cut -f3 "${test_dir}/curl.log" | jq -s -e \
  'any(.[]; .type == "A" and .name == "billing-selfhost-uat.onwalk.net" and .content == "192.0.2.138")' >/dev/null
cut -f3 "${test_dir}/curl.log" | jq -s -e \
  'any(.[]; .type == "A" and .name == "postgresql-selfhost-uat.onwalk.net" and .content == "192.0.2.138")' >/dev/null
cut -f3 "${test_dir}/curl.log" | jq -s -e \
  'any(.[]; .type == "A" and .name == "bridge-uat.onwalk.net" and .content == "192.0.2.138")' >/dev/null
cut -f3 "${test_dir}/curl.log" | jq -s -e \
  'any(.[]; .type == "A" and .name == "jp-xconnect.onwalk.net" and .content == "167.179.105.137")' >/dev/null
cut -f3 "${test_dir}/curl.log" | jq -s -e \
  'any(.[]; .type == "A" and .name == "us-xconnect.onwalk.net" and .content == "167.179.110.129")' >/dev/null

# The UAT DNS reconciler must fail closed for PROD before making any API call.
set +e
prod_output="$({
  PATH="${test_dir}/bin:${PATH}" \
  MOCK_CURL_LOG="${test_dir}/prod-curl.log" \
  CLOUDFLARE_DNS_API_TOKEN="test-token" \
  CLOUDFLARE_API_BASE_OVERRIDE="https://cloudflare.invalid/client/v4" \
  DEPLOY_ENV="prod" \
  SOURCE_DOMAIN_BASE="svc.plus" \
  TARGET_DOMAIN_BASE="onwalk.net" \
  CMDB_FILE="${test_dir}/cmdb.json" \
  GITOPS_ROUTING_CONFIG="${test_dir}/routing.json" \
  "${reconciler}"
} 2>&1)"
prod_exit=$?
set -e

[[ "${prod_exit}" -ne 0 ]]
grep -Fq 'UAT DNS reconciler requires DEPLOY_ENV=uat.' <<<"${prod_output}"
[[ ! -e "${test_dir}/prod-curl.log" ]]

cat >"${test_dir}/duplicate-cmdb.json" <<'EOF'
{
  "environment": "uat",
  "project_id": "open-platform-uat",
  "cloud_run_uri": null,
  "declared_spot_vms": ["web-saas-uat"],
  "spot_instances": {},
  "console-uat.onwalk.net": {
    "ip": "45.77.128.182",
    "groups": ["web_saas"]
  },
  "jp-xconnect.onwalk.net": {
    "ip": "45.77.128.182",
    "groups": ["agent_proxy"]
  }
}
EOF

set +e
duplicate_output="$({
  PATH="${test_dir}/bin:${PATH}" \
  MOCK_CURL_LOG="${test_dir}/duplicate-curl.log" \
  CLOUDFLARE_DNS_API_TOKEN="test-token" \
  CLOUDFLARE_API_BASE_OVERRIDE="https://cloudflare.invalid/client/v4" \
  DEPLOY_ENV="uat" \
  SOURCE_DOMAIN_BASE="svc.plus" \
  TARGET_DOMAIN_BASE="onwalk.net" \
  CMDB_FILE="${test_dir}/duplicate-cmdb.json" \
  GITOPS_ROUTING_CONFIG="${test_dir}/routing.json" \
  "${reconciler}"
} 2>&1)"
duplicate_exit=$?
set -e

[[ "${duplicate_exit}" -ne 0 ]]
grep -Fq 'agent-proxy host jp-xconnect.onwalk.net shares Web SaaS IP 45.77.128.182' <<<"${duplicate_output}"

# A canonical public entry that already exists belongs to whoever published it
# -- in UAT that is the serverless orchestrator's Worker custom domain, which
# Cloudflare refuses to let the DNS API delete. The reconciler must yield it
# instead of trying to reclaim it.
mkdir -p "${test_dir}/owned-bin"
cat >"${test_dir}/owned-bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

method="GET"
body=""
url="${!#}"
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --request)
      method="$2"
      shift 2
      ;;
    --data)
      body="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

printf '%s\t%s\t%s\n' "${method}" "${url}" "${body}" >>"${MOCK_CURL_LOG}"
if [[ "${url}" == *'/zones?name='* ]]; then
  printf '%s' '{"success":true,"result":[{"id":"zone-1"}]}'
elif [[ "${method}" == "GET" && "${url}" == *'name=console-uat.onwalk.net'* ]]; then
  printf '%s' '{"success":true,"result":[{"id":"worker-managed-1","type":"A","name":"console-uat.onwalk.net","content":"192.0.2.1","ttl":1,"proxied":true}]}'
elif [[ "${method}" == "GET" ]]; then
  printf '%s' '{"success":true,"result":[]}'
else
  printf '%s' '{"success":true,"result":{"id":"record-1"}}'
fi
EOF
chmod +x "${test_dir}/owned-bin/curl"

owned_output="$({
  PATH="${test_dir}/owned-bin:${PATH}" \
  MOCK_CURL_LOG="${test_dir}/owned-curl.log" \
  CLOUDFLARE_DNS_API_TOKEN="test-token" \
  CLOUDFLARE_API_BASE_OVERRIDE="https://cloudflare.invalid/client/v4" \
  DEPLOY_ENV="uat" \
  SOURCE_DOMAIN_BASE="svc.plus" \
  TARGET_DOMAIN_BASE="onwalk.net" \
  CMDB_FILE="${test_dir}/cmdb.json" \
  GITOPS_ROUTING_CONFIG="${test_dir}/routing.json" \
  "${reconciler}"
} 2>&1)"

grep -Fq 'Yielded console-uat.onwalk.net; held by the current owner (A -> 192.0.2.1)' <<<"${owned_output}"
grep -Fq 'Created accounts-uat.onwalk.net -> accounts-selfhost-uat.onwalk.net (CNAME)' <<<"${owned_output}"
# Reclaiming the record is exactly what returned HTTP 400 in run 32219402202.
if grep -q '^DELETE' "${test_dir}/owned-curl.log"; then
  echo "Expected no DNS record deletion while a canonical entry is owned elsewhere" >&2
  exit 1
fi
if grep -E '^(POST|PUT)' "${test_dir}/owned-curl.log" | grep -Fq 'console-uat.onwalk.net'; then
  echo "Expected no write against a canonical entry owned elsewhere" >&2
  exit 1
fi
if cut -f3 "${test_dir}/owned-curl.log" | jq -s -e \
  'any(.[]; .name == "console-uat.onwalk.net")' >/dev/null; then
  echo "Expected no desired payload for a canonical entry owned elsewhere" >&2
  exit 1
fi

echo "platform_ops_uat_dns_target_records_test: PASS"
