#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="${script_dir}/../reconcile-terraform-state.sh"
workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT

mkdir -p "${workdir}/bin"
cat >"${workdir}/state.json" <<'JSON'
{
  "values": {
    "root_module": {
      "resources": [],
      "child_modules": [
        {
          "address": "module.compute_console_nat_onwalk_net",
          "resources": [
            {
              "address": "module.compute_console_nat_onwalk_net.vultr_instance.this",
              "mode": "managed",
              "type": "vultr_instance",
              "values": {"id": "stale-instance-id"}
            }
          ],
          "child_modules": []
        }
      ]
    }
  }
}
JSON

cat >"${workdir}/bin/terraform" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  workspace) exit 0 ;;
  state)
    if [[ "${2:-}" == pull ]]; then
      cat "${TEST_WORKDIR}/state.json"
    elif [[ "${2:-}" == rm ]]; then
      printf '%s\n' "${*:3}" >"${TEST_WORKDIR}/state-rm-args"
    fi
    ;;
  *) echo "unexpected terraform invocation: $*" >&2; exit 1 ;;
esac
SCRIPT
chmod +x "${workdir}/bin/terraform"

cat >"${workdir}/bin/curl" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
body=''
while (($#)); do
  case "$1" in
    -o) body="$2"; shift 2 ;;
    -w) shift 2 ;;
    *) shift ;;
  esac
done
printf '{}' >"${body}"
printf '404'
SCRIPT
chmod +x "${workdir}/bin/curl"

TEST_WORKDIR="${workdir}" \
PATH="${workdir}/bin:${PATH}" \
ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE=test-workspace \
VULTR_API_KEY=test-key \
GITHUB_STEP_SUMMARY="${workdir}/summary.md" \
bash "${script}"

grep -Fq 'module.compute_console_nat_onwalk_net.vultr_instance.this' "${workdir}/state-rm-args"
grep -Fq 'removed 1 state entr' "${workdir}/summary.md"

# `terraform state pull` returns the legacy top-level resources[] shape. Keep
# the same nested module address covered so the production failure cannot
# regress when the backend state is read directly.
cat >"${workdir}/state.json" <<'JSON'
{
  "resources": [
    {
      "module": "module.compute_agent_proxy_node_uat",
      "mode": "managed",
      "type": "vultr_instance",
      "name": "this",
      "instances": [
        {"attributes": {"id": "stale-agent-proxy-id"}}
      ]
    }
  ]
}
JSON

TEST_WORKDIR="${workdir}" \
PATH="${workdir}/bin:${PATH}" \
ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE=test-workspace \
VULTR_API_KEY=test-key \
GITHUB_STEP_SUMMARY="${workdir}/summary.md" \
bash "${script}"

grep -Fq 'module.compute_agent_proxy_node_uat.vultr_instance.this' "${workdir}/state-rm-args"
grep -Fq 'removed 1 state entr' "${workdir}/summary.md"
echo "nested module stale-state reconcile test passed"
