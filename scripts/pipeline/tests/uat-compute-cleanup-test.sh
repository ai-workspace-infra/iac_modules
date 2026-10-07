#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/runtime"
export RUNNER_TEMP="$tmp/runtime" GITHUB_OUTPUT="$tmp/output" GITHUB_RUN_ID=123 GITHUB_RUN_ATTEMPT=1
export CLEANUP_OWNER_SHA=1111111111111111111111111111111111111111 CLEANUP_POLICY="$tmp/policy.yaml"
export MOCK_ROOT="$tmp" PATH="$tmp/bin:$PATH"
cat > "$tmp/bin/gcloud" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "$MOCK_ROOT/calls"
if [[ "$1 $2 $3" == 'run services list' ]]; then
  [[ ! -f "$MOCK_ROOT/list-fail" ]] || exit 1
  if [[ -f "$MOCK_ROOT/deleted" && ! -f "$MOCK_ROOT/still-present" ]]; then echo '[]';
  else echo '[{"metadata":{"name":"uat-accounts"}},{"metadata":{"name":"prod-accounts"}}]'; fi
elif [[ "$1 $2 $3" == 'run services delete' ]]; then
  [[ "$4" == uat-accounts ]] || exit 3
  [[ ! -f "$MOCK_ROOT/delete-fail" ]] || exit 1
  touch "$MOCK_ROOT/deleted"
else exit 2; fi
MOCK
chmod 755 "$tmp/bin/gcloud"
fixture() {
  rm -f "$tmp"/calls "$tmp"/deleted "$tmp"/delete-fail "$tmp"/list-fail "$tmp"/still-present "$RUNNER_TEMP/uat-compute-cleanup-receipt.json"
  cat > "$CLEANUP_POLICY" <<'YAML'
kind: ServerlessCleanupPolicy
metadata: {environment: uat}
spec:
  enabled: true
  project_id: open-platform-uat
  region: asia-east1
  services: [uat-accounts]
YAML
  export CLEANUP_MODE=apply
}
reject() {
  if bash "$root/uat-compute-cleanup.sh" > "$tmp/log" 2>&1; then echo "Unexpected acceptance: $1" >&2; exit 1; fi
  [[ ! -e "$RUNNER_TEMP/uat-compute-cleanup-receipt.json" ]]
  echo "PASS reject $1"
}
fixture; CLEANUP_MODE=plan bash "$root/uat-compute-cleanup.sh" >/dev/null
jq -e '.status == "plan-only" and .accepted == false' "$RUNNER_TEMP/uat-compute-cleanup-receipt.json" >/dev/null
! grep -q 'services delete' "$tmp/calls"; echo 'PASS plan never deletes'
fixture; yq -i '.spec.enabled = false' "$CLEANUP_POLICY"; reject disabled; [[ ! -e "$tmp/calls" ]]
fixture; yq -i '.metadata.environment = "prod"' "$CLEANUP_POLICY"; reject prod; [[ ! -e "$tmp/calls" ]]
fixture; yq -i '.spec.services = ["prod-accounts"]' "$CLEANUP_POLICY"; reject 'out-of-scope service'
fixture; touch "$tmp/list-fail"; reject 'failed facts query'; ! grep -q 'services delete' "$tmp/calls"
fixture; touch "$tmp/delete-fail"; reject 'failed deletion'
fixture; touch "$tmp/still-present"; reject 'resource remains after deletion'
fixture; bash "$root/uat-compute-cleanup.sh" >/dev/null
jq -e '.accepted == true and .status == "verified-deletion" and .environment == "uat" and .images_pruned == false' "$RUNNER_TEMP/uat-compute-cleanup-receipt.json" >/dev/null
echo 'PASS verified deletion and bounded scope'
echo '8 cleanup checks passed using a mock Provider; no cloud resource changed.'
