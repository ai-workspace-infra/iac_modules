#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
temporary="$(mktemp -d)"
trap 'rm -rf "$temporary"' EXIT
mkdir -p "$temporary/bin" "$temporary/lab" "$temporary/gitops" "$temporary/iac/vpn-overlay" "$temporary/iac/scripts/pipeline"
cp -R "$root/vpn-overlay/xconnect-lab" "$temporary/iac/vpn-overlay/xconnect-lab"
cp "$root/scripts/pipeline/xconnect-lab-contract.py" "$temporary/iac/scripts/pipeline/"
cp "$root/scripts/pipeline/xconnect-terraform-diagnostics.py" "$temporary/iac/scripts/pipeline/"
cp "$root/scripts/pipeline/xconnect-lab-lease.sh" "$temporary/iac/scripts/pipeline/"

cat > "$temporary/bin/terraform" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
command="$2"
echo "$command" >> "$MOCK_CALLS"
case "$command" in
  apply|destroy) printf '{"type":"change_summary"}\n' ;;
  output) printf '{"gateway":{}}\n' ;;
  show) printf '{"values":{"root_module":{"resources":[]}}}\n' ;;
  state) : ;;
  *) exit 9 ;;
esac
SH
cat > "$temporary/bin/aws" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$MOCK_AWS_CALLS"
SH
chmod 755 "$temporary/bin/terraform" "$temporary/bin/aws"

cat > "$temporary/gitops/lab.json" <<'JSON'
{"spec":{"gateway_provider":"external","aws":{"region":"ap-northeast-1"},"nodes":{"one":{"instance_type":"t4g.micro"},"gateway":{"instance_type":"t4g.small"}},"zero":{"accounts_api_url":"https://accounts-uat.onwalk.net","portal_url":"https://console-serverless-uat.onwalk.net/panel/xconnect-zero"}}}
JSON
printf 'xcl-123-1' > "$temporary/lab/run-id"
touch "$temporary/lab/backend-ready" "$temporary/lab/plan"
printf '{"expires_at":"2030-01-01T00:00:00Z"}' > "$temporary/lab/variables.json"

export PATH="$temporary/bin:$PATH"
export RUNNER_TEMP="$temporary"
export LAB_DIR="$temporary/lab"
export IAC_ROOT="$temporary/iac"
export GITOPS_ROOT="$temporary/gitops"
export XCONNECT_DECLARATION="$temporary/gitops/lab.json"
export TF_VAR_run_id=xcl-123-1 MODE=apply XCONNECT_IAC_OPERATION=apply
export MOCK_CALLS="$temporary/terraform-calls" MOCK_AWS_CALLS="$temporary/aws-calls"
export TF_STATE_ACCESS_KEY=test TF_STATE_SECRET_KEY=test TF_STATE_REGION=auto
export TF_STATE_ENDPOINT=https://state.invalid TF_STATE_BUCKET=test
IAC_REF="$(printf 'a%.0s' {1..40})"
GITOPS_REF="$(printf 'b%.0s' {1..40})"
PLAYBOOKS_REF="$(printf 'c%.0s' {1..40})"
export IAC_REF GITOPS_REF PLAYBOOKS_REF
export CLI_RELEASE_TAG=v1 GATEWAY_RELEASE_TAG=v1 XRAY_RELEASE_TAG=v1

bash "$root/scripts/pipeline/xconnect-lab-lifecycle.sh"
grep -Fxq apply "$MOCK_CALLS"
grep -Fxq output "$MOCK_CALLS"
grep -Fq 's3api put-object' "$MOCK_AWS_CALLS"
test -s "$LAB_DIR/outputs.json"

: > "$MOCK_CALLS"
: > "$MOCK_AWS_CALLS"
export MODE=cleanup XCONNECT_IAC_OPERATION=cleanup
bash "$root/scripts/pipeline/xconnect-lab-lifecycle.sh"
grep -Fxq show "$MOCK_CALLS"
grep -Fxq destroy "$MOCK_CALLS"
grep -Fxq state "$MOCK_CALLS"
grep -Fq 's3api delete-object' "$MOCK_AWS_CALLS"
if grep -Eq 'ssh|ansible|systemctl|curl' "$MOCK_CALLS" "$MOCK_AWS_CALLS"; then
  echo 'IaC lifecycle invoked a host/service command' >&2
  exit 1
fi
echo 'xconnect-lab-lifecycle-test: PASS'
