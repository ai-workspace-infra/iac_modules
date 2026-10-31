#!/usr/bin/env bash
# Side-effect-free contract test for the GCP org identity owner scripts.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
dir="$root/scripts/pipeline/maintenance/gcp"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
# Cloud Run owner keeps the OTEL contract ported from Orchestrator
grep -q 'OTEL_SERVICE_NAME=${SERVICE_NAME}' "$root/scripts/pipeline/deploy-cloudrun-services.sh"
if ! command -v ruby >/dev/null 2>&1; then
  echo 'gcp_org_identity_owner_test: ruby unavailable, declaration checks skipped'; exit 0
fi
cat > "$tmp/ns.yaml" <<'Y'
kind: GCPWorkloadNamespace
metadata: {environment: shared, provider: gcp}
spec:
  project_id: open-platform-test1
  gcp_account_id: open-platform-shared
  external_ip_allowed_instances:
    - {name: gw-1, zone: asia-east1-b}
Y
out="$(bash "$dir/seed_shared_external_ip_policy.sh" --manifest "$tmp/ns.yaml" --render)"
grep -q 'projects/open-platform-test1/zones/asia-east1-b/instances/gw-1' <<<"$out"
grep -q 'compute.vmExternalIpAccess' <<<"$out"
# render mode must never reach gcloud
! grep -n 'gcloud' <<<"$out" >/dev/null
# duplicate entries rejected
printf '    - {name: gw-1, zone: asia-east1-b}\n' >> "$tmp/ns.yaml"
if bash "$dir/seed_shared_external_ip_policy.sh" --manifest "$tmp/ns.yaml" --render >/dev/null 2>&1; then
  echo 'duplicate allowlist must fail' >&2; exit 1
fi
# OIDC resolver rejects an invalid environment without reading cloud state
if GCP_ENVIRONMENT=dev GCP_OIDC_CONFIG="$tmp/ns.yaml" bash "$dir/resolve_github_oidc_config.sh" >/dev/null 2>&1; then
  echo 'invalid env must fail' >&2; exit 1
fi
echo 'gcp_org_identity_owner_test: ok'
