#!/usr/bin/env bash
set -euo pipefail
task_dir="$(mktemp -d)"
trap 'rm -rf "$task_dir"' EXIT
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
mkdir "$task_dir/bin"
cat > "$task_dir/bin/timeout" <<'EOF'
#!/usr/bin/env bash
shift
exec "$@"
EOF
cat > "$task_dir/bin/gcloud" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$OSLOGIN_TEST_LOG"
key=''
for arg in "$@"; do [[ "$arg" != --key-file=* ]] || key="${arg#--key-file=}"; done
[[ -f "$key" && ! -f "${key%.pub}" ]]
[[ "$*" == *'--account=github-actions-prod@test-project.iam.gserviceaccount.com'* ]]
[[ "$*" == *'--project=test-project'* ]]
if [[ "$*" == *'ssh-keys add'* ]]; then
  [[ "$*" == *'--ttl=1m'* ]]
  [[ "${OSLOGIN_TEST_FAIL:-}" != add ]]
else
  [[ "$*" == *'ssh-keys remove'* ]]
  [[ "${OSLOGIN_TEST_FAIL:-}" != remove ]]
fi
EOF
chmod +x "$task_dir/bin/timeout" "$task_dir/bin/gcloud"
export PATH="$task_dir/bin:$PATH"
export GOOGLE_GHA_CREDS_PATH="$task_dir/wif.json"
export OSLOGIN_TEST_LOG="$task_dir/calls"
cat > "$GOOGLE_GHA_CREDS_PATH" <<'EOF'
{"type":"external_account","service_account_impersonation_url":"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/github-actions-prod@test-project.iam.gserviceaccount.com:generateAccessToken"}
EOF
owner="$repo/scripts/pipeline/initialize-gcp-oslogin-profile.sh"
bash "$owner" test-project github-actions-prod@test-project.iam.gserviceaccount.com
[[ "$(wc -l < "$OSLOGIN_TEST_LOG" | tr -d ' ')" == 2 ]]
for failure in add remove; do
  : > "$OSLOGIN_TEST_LOG"
  if OSLOGIN_TEST_FAIL="$failure" bash "$owner" test-project github-actions-prod@test-project.iam.gserviceaccount.com > "$task_dir/output" 2>&1; then
    echo 'Expected initialization/revocation refusal.' >&2; exit 1
  fi
  [[ "$(wc -l < "$OSLOGIN_TEST_LOG" | tr -d ' ')" == 2 ]]
done
for principal in person@example.com github-actions-prod@other-project.iam.gserviceaccount.com; do
  : > "$OSLOGIN_TEST_LOG"
  if bash "$owner" test-project "$principal" > "$task_dir/output" 2>&1; then exit 1; fi
  [[ ! -s "$OSLOGIN_TEST_LOG" ]]
done
printf '{"type":"authorized_user"}\n' > "$GOOGLE_GHA_CREDS_PATH"
if bash "$owner" test-project github-actions-prod@test-project.iam.gserviceaccount.com > "$task_dir/output" 2>&1; then exit 1; fi
[[ ! -s "$OSLOGIN_TEST_LOG" ]]
echo 'Bounded OS Login first-profile contract checks passed.'
