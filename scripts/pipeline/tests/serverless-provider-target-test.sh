#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/runtime"
export PATH="$tmp/bin:$PATH" MOCK_ROOT="$tmp" RUNNER_TEMP="$tmp/runtime" GITHUB_OUTPUT="$tmp/output"
export GITHUB_ACTION_PATH="$root/.github/actions/serverless-provider-operations" GITHUB_RUN_ID=100 GITHUB_RUN_ATTEMPT=1
export PROVIDER_OPERATION=registry-preflight PROVIDER_ENVIRONMENT=uat PROVIDER_RELEASE_REF=v2026.10.07 PROVIDER_OWNER_SHA=1111111111111111111111111111111111111111
export GCP_DECLARATION="$tmp/namespace" CLOUDFLARE_BOUNDARY_CONFIG="$tmp/routing" GCP_PROJECT_ID=open-platform-uat GCP_REGION=asia-east1 CLOUD_RUN_SERVICE=accounts
yq -r '.runs.steps[0].run' "$GITHUB_ACTION_PATH/action.yml" > "$tmp/action-run"
cat > "$tmp/bin/gcloud" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1 $2 $3 $4" == 'artifacts repositories describe serverless' ]] || exit 2
printf 'called\n' >> "$MOCK_ROOT/calls"
MOCK
chmod 755 "$tmp/bin/gcloud"
fixture() {
  rm -f "$tmp/output" "$tmp/calls"
  echo 'global: {environment: uat, project_id: open-platform-uat, region: asia-east1}' > "$GCP_DECLARATION"
  echo '{"kind":"EdgeRoutingConfig","metadata":{"environment":"uat"}}' > "$CLOUDFLARE_BOUNDARY_CONFIG"
}
reject() { if bash "$tmp/action-run" >/dev/null 2>&1; then exit 1; fi; [[ ! -e "$tmp/calls" && ! -s "$tmp/output" ]]; echo "PASS reject $1 before Provider query"; }
fixture; bash "$tmp/action-run" >/dev/null
receipt="$(sed -n 's/^receipt=//p' "$GITHUB_OUTPUT")"
jq -e '.accepted == true and .operation == "registry-preflight" and .target == "accounts" and .run_id == "100"' "$receipt" >/dev/null
echo 'PASS bound Registry query and exact owner receipt'
fixture; yq -i '.global.environment = "prod"' "$GCP_DECLARATION"; reject 'different namespace environment'
fixture; yq -i '.global.project_id = "open-platform-prod"' "$GCP_DECLARATION"; reject 'different namespace project'
fixture; yq -i '.global.region = "us-central1"' "$GCP_DECLARATION"; reject 'different namespace region'
echo '4 Provider target checks passed with a mock SDK.'
