#!/usr/bin/env bash
# Isolation test: external-ip-policy is shared-only, and env/declaration
# mismatches fail before any gcloud call. Uses a fake gcloud; no cloud access.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
entry="$root/scripts/pipeline/gcp-org-identity.sh"
seed="$root/scripts/pipeline/maintenance/gcp/seed_shared_external_ip_policy.sh"
t="$(mktemp -d)"; trap 'rm -rf "$t"' EXIT
mkdir -p "$t/bin" "$t/runner"
printf '#!/usr/bin/env bash\necho "$*" >> "%s/gcloud.calls"\nexit 0\n' "$t" > "$t/bin/gcloud"; chmod +x "$t/bin/gcloud"
export PATH="$t/bin:$PATH" RUNNER_TEMP="$t/runner"
fail() { echo "FAIL: $*" >&2; exit 1; }
decl() { cat > "$t/$1.yaml" <<Y
kind: GCPWorkloadNamespace
metadata: {environment: $1, provider: gcp}
spec:
  project_id: open-platform-test1
  gcp_account_id: open-platform-shared
  external_ip_allowed_instances:
    - {name: gw-1, zone: asia-east1-b}
Y
}
decl shared; decl uat
run() { OP=external-ip-policy GCP_ENVIRONMENT="$1" DECLARATION="$t/$2.yaml" MODE="$3" bash "$entry"; }

# uat/prod inputs against a shared declaration must fail before gcloud, render or apply
for env in uat prod; do for mode in render apply; do
  run "$env" shared "$mode" >"$t/out" 2>&1 && fail "accepted environment=$env mode=$mode"
  grep -q 'shared-only' "$t/out" || fail "wrong error for $env/$mode: $(cat "$t/out")"
done; done
# direct script call with non-shared env also refuses
bash "$seed" --manifest "$t/shared.yaml" --environment uat --apply >/dev/null 2>&1 && fail "seed accepted --environment uat"
[[ ! -e "$t/gcloud.calls" ]] || fail "gcloud invoked: $(cat "$t/gcloud.calls")"
[[ -z "$(ls -A "$t/runner")" ]] || fail "receipt written on rejected input"

if command -v ruby >/dev/null 2>&1; then
  # shared input + uat declaration (mismatch) fails before gcloud
  run shared uat apply >/dev/null 2>&1 && fail "accepted declaration env mismatch"
  [[ ! -e "$t/gcloud.calls" ]] || fail "gcloud invoked on declaration mismatch"
  # shared render succeeds with a matching receipt and no gcloud
  r="$(run shared shared render)"
  jq -e '.accepted and .environment=="shared" and .declaration_environment=="shared" and .operation=="external-ip-policy" and .mode=="render"' "$r" >/dev/null || fail "bad receipt $(cat "$r")"
  [[ ! -e "$t/gcloud.calls" ]] || fail "render invoked gcloud"
else
  echo 'gcp-org-identity-env-test: ruby unavailable, declaration-match cases skipped'
fi
echo 'gcp-org-identity-env-test: ok'
