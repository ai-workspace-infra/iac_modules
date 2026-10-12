#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
reconciler="${repo_root}/scripts/pipeline/cloudflare-uat-dns-reconcile.sh"
test_dir="$(mktemp -d)"
trap 'rm -rf "${test_dir}"' EXIT
mkdir -p "${test_dir}/bin"

cat > "${test_dir}/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
method=GET
url="${!#}"
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --request) method="$2"; shift 2 ;;
    *) shift ;;
  esac
done
printf '%s\t%s\n' "${method}" "${url}" >> "${MOCK_CURL_LOG}"
if [[ "${url}" == *'/zones?name='* ]]; then
  printf '%s' '{"success":true,"result":[{"id":"zone-1"}]}'
elif [[ "${method}" == GET ]]; then
  printf '%s' '{"success":true,"result":[]}'
else
  printf '%s' '{"success":true,"result":{"id":"record-1"}}'
fi
EOF
chmod +x "${test_dir}/bin/curl"

cat > "${test_dir}/routing.json" <<'EOF'
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

cat > "${test_dir}/cmdb.json" <<'EOF'
{
  "jp-xconnect.onwalk.net": {
    "fqdn": "jp-xconnect.onwalk.net",
    "ip": "167.179.105.137",
    "groups": ["agent_proxy"]
  }
}
EOF

output="$({
  PATH="${test_dir}/bin:${PATH}" \
  MOCK_CURL_LOG="${test_dir}/curl.log" \
  CLOUDFLARE_DNS_API_TOKEN=test-token \
  CLOUDFLARE_API_BASE_OVERRIDE=https://cloudflare.invalid/client/v4 \
  DEPLOY_ENV=uat TARGET_DOMAINS=agent-proxy \
  SOURCE_DOMAIN_BASE=svc.plus TARGET_DOMAIN_BASE=onwalk.net \
  CMDB_FILE="${test_dir}/cmdb.json" GITOPS_ROUTING_CONFIG="${test_dir}/routing.json" \
  "${reconciler}"
} 2>&1)"

grep -Fq 'Created jp-xconnect.onwalk.net -> 167.179.105.137 (A)' <<< "${output}"
grep -Fq 'completed for 1 Agent Proxy records' <<< "${output}"
if grep -Fq 'console-selfhost-uat.onwalk.net' "${test_dir}/curl.log"; then
  echo 'Agent Proxy-only DNS must not reconcile Web SaaS records' >&2
  exit 1
fi

echo "platform_ops_agent_proxy_uat_dns_test: PASS"
