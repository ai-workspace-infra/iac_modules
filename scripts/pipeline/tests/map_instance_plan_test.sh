#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
script="${repo_root}/scripts/pipeline/map-instance-plan.sh"

assert_contains() {
  local output="$1" expected="$2"
  if ! grep -Fqx "${expected}" <<<"${output}"; then
    echo "expected '${expected}' in instance plan output:" >&2
    echo "${output}" >&2
    exit 1
  fi
}

akamai_plan_output="$(mktemp)"
INPUT_CLOUD_PROVIDER=akamai-cloud INPUT_INSTANCE_PLAN=2C8G GITHUB_OUTPUT="${akamai_plan_output}" \
  "${script}"
assert_contains "$(cat "${akamai_plan_output}")" "api=g8-dedicated-8-2"
rm -f "${akamai_plan_output}"

agent_proxy_plan_output="$(mktemp)"
INPUT_CLOUD_PROVIDER=aws-cloud INPUT_INSTANCE_PLAN=2C2G INPUT_AGENT_PROXY_PLAN=2C2G GITHUB_OUTPUT="${agent_proxy_plan_output}" \
  "${script}"
assert_contains "$(cat "${agent_proxy_plan_output}")" "api=t4g.small"
assert_contains "$(cat "${agent_proxy_plan_output}")" "agent_api=t4g.small"
rm -f "${agent_proxy_plan_output}"

echo "map_instance_plan_test: PASS"
