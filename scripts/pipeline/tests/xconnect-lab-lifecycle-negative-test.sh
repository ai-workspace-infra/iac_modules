#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
temporary="$(mktemp -d)"
mkdir -p "$temporary/bin" "$temporary/gitops"

cat > "$temporary/bin/terraform" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
command="$2"
printf '%s\n' "$command" >> "$MOCK_CALLS"
if [[ "$command" == "${FAIL_TF_COMMAND:-}" ]]; then
  if [[ "$command" == apply ]]; then
    printf '%s\n' '{"type":"diagnostic","diagnostic":{"severity":"error","address":"aws_instance.gateway","summary":"private-instance","detail":"ModifyInstanceAttribute Unsupported secret-apply-token"}}'
    exit 7
  fi
  echo 'AccessDenied secret-read-token' >&2
  exit 9
fi
case "$command" in
  apply|destroy) printf '%s\n' '{"type":"change_summary"}' ;;
  output) printf '%s\n' '{"gateway":{}}' ;;
  show) printf '%s\n' '{"values":{"root_module":{"resources":[]}}}' ;;
  state) : ;;
  *) exit 2 ;;
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

export PATH="$temporary/bin:$PATH"
export RUNNER_TEMP="$temporary" IAC_ROOT="$root" GITOPS_ROOT="$temporary/gitops"
export XCONNECT_DECLARATION="$temporary/gitops/lab.json" TF_VAR_run_id=xcl-123-5
export IAC_REF="$(printf 'a%.0s' {1..40})" GITOPS_REF="$(printf 'b%.0s' {1..40})" PLAYBOOKS_REF="$(printf 'c%.0s' {1..40})"
export CLI_RELEASE_TAG=v0.1.14 GATEWAY_RELEASE_TAG=v0.1.8 XRAY_RELEASE_TAG=v26.3.27
export TF_STATE_ACCESS_KEY=test TF_STATE_SECRET_KEY=test TF_STATE_REGION=auto
export TF_STATE_ENDPOINT=https://state.invalid TF_STATE_BUCKET=state-bucket
export MOCK_AWS_CALLS="$temporary/aws-calls"

permissions() {
  stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1"
}

prepare_lab() {
  local name="$1"
  LAB_DIR="$temporary/$name"
  export LAB_DIR MOCK_CALLS="$LAB_DIR/terraform-calls" GITHUB_STEP_SUMMARY="$LAB_DIR/summary"
  mkdir -p "$LAB_DIR"
  printf 'xcl-123-5' > "$LAB_DIR/run-id"
  touch "$LAB_DIR/backend-ready" "$LAB_DIR/plan"
  printf '%s' '{"expires_at":"2030-01-01T00:00:00Z"}' > "$LAB_DIR/variables.json"
}

expect_failure() {
  local expected="$1" output="$2"; shift 2
  set +e
  "$@" >"$output.stdout" 2>"$output.stderr"
  local actual=$?
  set -e
  [[ "$actual" == "$expected" ]] || {
    echo "expected exit $expected, got $actual" >&2
    sed -n '1,120p' "$output.stdout" "$output.stderr" >&2
    exit 1
  }
}

assert_sanitized() {
  local output="$1" secret="$2" log="$3"
  grep -Fq "$secret" "$log"
  [[ "$(permissions "$log")" == 600 ]]
  if grep -Fq "$secret" "$output.stdout" "$output.stderr" "$GITHUB_STEP_SUMMARY"; then
    echo 'raw Terraform diagnostic escaped the private log' >&2
    exit 1
  fi
}

prepare_lab apply-failure
printf 'earlier-destroy-evidence' > "$LAB_DIR/terraform-destroy.log"
export MODE=apply XCONNECT_IAC_OPERATION=apply FAIL_TF_COMMAND=apply
expect_failure 7 "$LAB_DIR/result" bash "$root/scripts/pipeline/xconnect-lab-lifecycle.sh"
assert_sanitized "$LAB_DIR/result" secret-apply-token "$LAB_DIR/terraform-apply.log"
grep -Fxq earlier-destroy-evidence "$LAB_DIR/terraform-destroy.log"

prepare_lab output-failure
export MODE=apply XCONNECT_IAC_OPERATION=apply FAIL_TF_COMMAND=output
expect_failure 9 "$LAB_DIR/result" bash "$root/scripts/pipeline/xconnect-lab-lifecycle.sh"
assert_sanitized "$LAB_DIR/result" secret-read-token "$LAB_DIR/terraform-output.log"
grep -Fq 'cleanup is unverified and requires exact-run recovery' "$LAB_DIR/result.stderr"
if grep -Fxq destroy "$MOCK_CALLS"; then
  echo 'output failure continued into destroy' >&2
  exit 1
fi

prepare_lab show-failure
export MODE=cleanup XCONNECT_IAC_OPERATION=cleanup FAIL_TF_COMMAND=show
expect_failure 9 "$LAB_DIR/result" bash "$root/scripts/pipeline/xconnect-lab-lifecycle.sh"
assert_sanitized "$LAB_DIR/result" secret-read-token "$LAB_DIR/terraform-show.log"
grep -Fq 'cleanup is unverified and requires exact-run recovery' "$LAB_DIR/result.stderr"
if grep -Fxq destroy "$MOCK_CALLS"; then
  echo 'state read failure continued into destroy' >&2
  exit 1
fi

echo 'xconnect-lab-lifecycle-negative-test: PASS'
