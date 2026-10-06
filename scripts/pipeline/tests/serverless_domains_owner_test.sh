#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
reconciler="${repo_root}/scripts/pipeline/cloudflare-serverless-domains-reconcile.sh"
test_dir="$(mktemp -d)"
trap 'rc=$?; rm -rf "${test_dir}"; exit ${rc}' EXIT

mkdir -p "${test_dir}/bin"
cat >"${test_dir}/routing.json" <<'EOF'
{
  "kind": "EdgeRoutingConfig",
  "metadata": {"mode": "serverless"},
  "spec": {
    "runtime": {
      "mode": "serverless",
      "routing": {
        "dns": {
          "canonical_records": {
      "console-uat.onwalk.net": "console-serverless-uat.onwalk.net",
      "accounts-uat.onwalk.net": "accounts-serverless-uat.onwalk.net"
          }
        }
      }
    },
    "domains": {
      "console-uat.onwalk.net": {
        "selfhost": "console-selfhost-uat.onwalk.net",
        "serverless": "console-serverless-uat.onwalk.net"
      },
      "accounts-uat.onwalk.net": {
        "selfhost": "accounts-selfhost-uat.onwalk.net",
        "serverless": "accounts-serverless-uat.onwalk.net"
      }
    },
    "cloudflare": {
      "zone_name": "onwalk.net",
      "pages_project": "ai-workspace-portal-uat"
    },
    "serverless": {
      "console_host": "console-serverless-uat.onwalk.net",
      "console_aliases": ["console-serverless-uat.example.com"],
      "accounts_host": "accounts-serverless-uat.onwalk.net",
      "accounts_aliases": ["accounts-cloudflare-uat.onwalk.net"],
      "billing_host": "billing-uat.onwalk.net",
      "billing_origin_host": "billing-origin-serverless-uat.onwalk.net",
      "cloud_run": {
        "billing_service": "https://uat-billing-service-1004637461064.asia-northeast1.run.app"
      },
      "frontend_router": {
        "worker_name": "frontend-router-uat",
        "website": {"zone_name": "xworktech.com", "hosts": ["xworktech.com", "www.xworktech.com"], "platform_origin": "https://svc.plus"}
      },
      "edge_gateway": {
        "boundaries": [
          {"id": "core", "display_name": "Edge Gateway Router Core", "worker_name": "edge-gateway-core-uat"}
        ]
      }
    }
  }
}
EOF

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
if [[ "${method}" == 'DELETE' && "${url}" == *'/dns_records/billing-cname' ]]; then
  touch "${MOCK_CURL_LOG}.billing-removed"
  printf '%s' '{"success":true,"result":{}}'
elif [[ "${method}" == 'DELETE' && "${url}" == *'/dns_records/billing-origin-cname' ]]; then
  printf '%s' '{"success":false,"result":null,"errors":[{"code":1043,"message":"Unable to edit this record as this has been configured as read only."}]}'
  exit 22
elif [[ "${url}" == *'/zones?name='* ]]; then
  printf '%s' '{"success":true,"result":[{"id":"zone-1"}]}'
elif [[ "${url}" == *'/pages/projects/ai-workspace-portal-uat/domains'* && "${method}" == 'GET' ]]; then
  printf '%s' '{"success":true,"result":[]}'
elif [[ "${url}" == *'/workers/domains'* && "${method}" == 'GET' ]]; then
  printf '%s' '{"success":true,"result":[{"id":"accounts-alias-worker-domain","hostname":"accounts-uat.onwalk.net","service":"edge-gateway-core-uat"}]}'
elif [[ "${url}" == *'/zones/zone-1/workers/routes' && "${method}" == 'GET' ]]; then
  printf '%s' '{"success":true,"result":[{"id":"stale-console-route","pattern":"console-serverless-uat.onwalk.net/_edge/public/*","script":"frontend-ssr-public-uat-uat"},{"id":"current-accounts-route","pattern":"accounts-serverless-uat.onwalk.net/api/*","script":"edge-gateway-core-uat"}]}'
elif [[ "${url}" == *'/rulesets?per_page=50' && "${method}" == 'GET' ]]; then
  printf '%s' '{"success":true,"result":[{"id":"ruleset-1","kind":"zone","phase":"http_request_origin"}]}'
elif [[ "${url}" == *'/rulesets/ruleset-1'* && "${method}" == 'GET' ]]; then
  printf '%s' '{"success":true,"result":{"id":"ruleset-1","rules":[{"ref":"existing_rule","action":"route","expression":"(http.host eq \\\"existing.example.com\\\")"}]}}'
elif [[ "${url}" == *'/dns_records?name=billing-uat.onwalk.net'* && "${method}" == 'GET' ]]; then
  if [[ -f "${MOCK_CURL_LOG}.billing-removed" ]]; then
    printf '%s' '{"success":true,"result":[]}'
  else
    printf '%s' '{"success":true,"result":[{"id":"billing-cname","type":"A","content":"198.51.100.10"}]}'
  fi
elif [[ "${url}" == *'/dns_records?name=billing-origin-serverless-uat.onwalk.net'* && "${method}" == 'GET' ]]; then
  printf '%s' '{"success":true,"result":[{"id":"billing-origin-cname","content":"uat-billing-service-1004637461064.asia-northeast1.run.app"}]}'
elif [[ "${url}" == *'/dns_records?name=console-uat.onwalk.net'* && "${method}" == 'GET' ]]; then
  printf '%s' '{"success":true,"result":[{"id":"console-alias","content":"console-selfhost-uat.onwalk.net"}]}'
elif [[ "${url}" == *'/dns_records?name=accounts-uat.onwalk.net'* && "${method}" == 'GET' ]]; then
  printf '%s' '{"success":true,"result":[{"id":"accounts-alias","content":"accounts-serverless-uat.onwalk.net"}]}'
elif [[ "${url}" == *'/dns_records?name='* && "${method}" == 'GET' ]]; then
  printf '%s' '{"success":true,"result":[]}'
else
  printf '%s' '{"success":true,"result":{}}'
fi
EOF
chmod +x "${test_dir}/bin/curl"

grep -Fq 'code == 1043 or .code == 1046' "${reconciler}"

PATH="${test_dir}/bin:${PATH}" \
MOCK_CURL_LOG="${test_dir}/curl.log" \
CLOUDFLARE_ACCOUNT_ID="account-1" \
CLOUDFLARE_API_TOKEN="test-token" \
CLOUDFLARE_BOUNDARY_CONFIG="${test_dir}/routing.json" \
CLOUDFLARE_API_BASE_OVERRIDE="https://cloudflare.invalid/client/v4" \
SERVERLESS_DNS_MODE="uat-records" \
"${reconciler}"

if grep -F $'GET	https://cloudflare.invalid/client/v4/zones?name=' "${test_dir}/curl.log" | grep -vF 'account.id=account-1' >/dev/null; then
  echo "Zone discovery must be scoped to the configured Cloudflare account" >&2
  exit 1
fi

if grep -Fq $'POST\thttps://cloudflare.invalid/client/v4/accounts/account-1/pages/projects/ai-workspace-portal-uat/domains' "${test_dir}/curl.log"; then
  echo "Pages must not receive the Console custom domain" >&2
  exit 1
fi
worker_puts="$(grep -Fc $'PUT\thttps://cloudflare.invalid/client/v4/accounts/account-1/workers/domains' "${test_dir}/curl.log")"
# Canonical aliases are now Worker custom domains too; alongside the console,
# console alias, website, accounts, accounts alias, and billing hosts this
# produces eight bindings.
test "${worker_puts}" -eq 8
worker_bodies="$(cut -f3 "${test_dir}/curl.log" | jq -s '[.[] | select(type == "object" and .hostname != null)]')"
if ! jq -e '
  ((map(select(.hostname == "billing-uat.onwalk.net" and .service == "edge-gateway-core-uat")) | length) == 1)
  and ((map(select(.hostname == "console-uat.onwalk.net" and .service == "frontend-router-uat")) | length) == 1)
  and ((map(select(.hostname == "console-serverless-uat.example.com" and .service == "frontend-router-uat" and .zone_name == "example.com")) | length) == 1)
  and ((map(select(.hostname == "accounts-uat.onwalk.net")) | length) == 0)
  and ((map(select(.hostname == "accounts-cloudflare-uat.onwalk.net" and .service == "edge-gateway-core-uat")) | length) == 1)
' <<<"${worker_bodies}" >/dev/null; then
  echo "Unexpected Worker custom-domain bindings: ${worker_bodies}" >&2
  exit 1
fi
dns_deletes="$(grep -Fc $'DELETE\thttps://cloudflare.invalid/client/v4/zones/zone-1/dns_records/' "${test_dir}/curl.log")"
# The canonical aliases remain Worker-bound; both stale records are inspected,
# while the managed origin record returns Cloudflare's read-only error and is
# intentionally left in place. Email Routing records return a different
# provider-managed error (1046), which must receive the same treatment.
test "${dns_deletes}" -eq 2
cname_bodies="$(cut -f3 "${test_dir}/curl.log" | jq -s '[.[] | select(.type == "CNAME")]')"
test "$(jq 'length' <<<"${cname_bodies}")" -eq 0
if grep -Fq '/rulesets' "${test_dir}/curl.log"; then
  echo "Billing must not depend on Enterprise-only Cloudflare Origin Rules" >&2
  exit 1
fi
grep -Fq $'DELETE\thttps://cloudflare.invalid/client/v4/zones/zone-1/workers/routes/stale-console-route' "${test_dir}/curl.log"
if grep -Fq $'DELETE\thttps://cloudflare.invalid/client/v4/zones/zone-1/workers/routes/current-accounts-route' "${test_dir}/curl.log"; then
  echo "Accounts boundary routes must be preserved" >&2
  exit 1
fi
for hostname in xworktech.com www.xworktech.com; do
  grep -F 'PUT' "${test_dir}/curl.log" | grep -F "\"hostname\":\"${hostname}\"" | grep -Fq '"zone_name":"xworktech.com"'
done
if grep -Fq '/zones?name=com&' "${test_dir}/curl.log"; then
  echo "Apex website binding used the TLD instead of its declared zone" >&2
  exit 1
fi
echo "serverless_domains_owner_legacy_test: PASS"

# After explicit GTM activation, routine publishing must not detach/rebind API
# canonical domains or remove their Routes, including dns_mode=none.
jq '
  .spec.runtime.routing.dns.api_alias_mode = "worker-routes-cname"
  | .spec.runtime.routing.dns.api_cname_records = {"accounts-uat.onwalk.net": {}, "billing-uat.onwalk.net": {}}
  | .spec.runtime.routing.dns.canonical_records["billing-uat.onwalk.net"] = "billing-serverless-uat.onwalk.net"
  | .spec.serverless.billing_serverless_host = "billing-serverless-uat.onwalk.net"
  | .spec.serverless.billing_origin_host = ""
  | .spec.serverless.accounts_aliases += ["accounts-uat.onwalk.net"]
' "${test_dir}/routing.json" > "${test_dir}/guarded.json"
for mode in none uat-records; do
  PATH="${test_dir}/bin:${PATH}" \
  MOCK_CURL_LOG="${test_dir}/${mode}.log" \
  CLOUDFLARE_ACCOUNT_ID="account-1" \
  CLOUDFLARE_API_TOKEN="test-token" \
  CLOUDFLARE_BOUNDARY_CONFIG="${test_dir}/guarded.json" \
  CLOUDFLARE_API_BASE_OVERRIDE="https://cloudflare.invalid/client/v4" \
  SERVERLESS_DNS_MODE="${mode}" \
  "${reconciler}"
  for hostname in accounts-uat.onwalk.net billing-uat.onwalk.net; do
    if grep -F 'PUT' "${test_dir}/${mode}.log" | grep -Fq "\"hostname\":\"${hostname}\""; then
      echo "Routine publisher rebound the GTM API alias" >&2; exit 1
    fi
  done
  if grep -Fq $'DELETE\thttps://cloudflare.invalid/client/v4/zones/zone-1/dns_records/billing-cname' "${test_dir}/${mode}.log" \
    || grep -Fq $'DELETE\thttps://cloudflare.invalid/client/v4/zones/zone-1/workers/routes/current-accounts-route' "${test_dir}/${mode}.log"; then
    echo "Routine publisher changed the stable API DNS/Route owner" >&2; exit 1
  fi
  grep -F 'PUT' "${test_dir}/${mode}.log" | grep -Fq '"hostname":"billing-serverless-uat.onwalk.net"'
done
echo "serverless_domains_owner_guarded_test: PASS"
