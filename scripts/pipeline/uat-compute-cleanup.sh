#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${CLEANUP_POLICY:?}" "${CLEANUP_MODE:?}" "${RUNNER_TEMP:?}" "${GITHUB_RUN_ID:?}" "${GITHUB_RUN_ATTEMPT:?}" "${GITHUB_OUTPUT:?}" "${CLEANUP_OWNER_SHA:?}"
[[ "$CLEANUP_OWNER_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 2
rm -f "$RUNNER_TEMP/uat-compute-cleanup-receipt.json"
case "$CLEANUP_MODE" in plan|apply) ;; *) exit 2 ;; esac
tmp="$(mktemp -d "$RUNNER_TEMP/uat-cleanup.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
trap 'echo "::error::UAT cleanup failed; no deletion acceptance was issued." >&2' ERR
yq -o=json '.' "$CLEANUP_POLICY" > "$tmp/policy"
jq -e '
  .kind == "ServerlessCleanupPolicy" and .metadata.environment == "uat" and
  (.spec.enabled | type == "boolean") and
  .spec.project_id == "open-platform-uat" and .spec.region == "asia-east1" and
  (.spec.services | type == "array" and length > 0 and length <= 3 and length == (unique|length) and
    all(.[]; . == "uat-accounts" or . == "uat-billing-service" or . == "uat-content-service"))
' "$tmp/policy" >/dev/null
project="$(jq -er '.spec.project_id' "$tmp/policy")"
region="$(jq -er '.spec.region' "$tmp/policy")"
# A disabled declaration must never reach a delete invocation.
if [[ "$CLEANUP_MODE" == apply ]]; then jq -e '.spec.enabled == true' "$tmp/policy" >/dev/null; fi
list_services() {
  gcloud run services list --project="$project" --region="$region" --format=json --quiet > "$1" 2>/dev/null
  jq -e 'type == "array" and all(.[]; .metadata.name | type == "string" and length > 0)' "$1" >/dev/null
}
list_services "$tmp/before"
jq --slurpfile policy "$tmp/policy" '[.[].metadata.name] as $existing |
  [$policy[0].spec.services[] | . as $name | {name:$name,present:($existing|index($name) != null)}]' \
  "$tmp/before" > "$tmp/targets"
if [[ "$CLEANUP_MODE" == apply ]]; then
  while IFS= read -r name; do
    gcloud run services delete "$name" --project="$project" --region="$region" --quiet >/dev/null 2>&1
  done < <(jq -r '.[] | select(.present) | .name' "$tmp/targets")
  list_services "$tmp/after"
  jq -e --slurpfile policy "$tmp/policy" '[.[].metadata.name] as $remaining |
    all($policy[0].spec.services[]; . as $name | $remaining | index($name) == null)' "$tmp/after" >/dev/null
  status=verified-deletion
else
  status=plan-only
fi
receipt="$RUNNER_TEMP/uat-compute-cleanup-receipt.json"
jq -n --arg status "$status" --arg owner "$CLEANUP_OWNER_SHA" \
  --arg run "$GITHUB_RUN_ID" --arg attempt "$GITHUB_RUN_ATTEMPT" \
  --arg project "$project" --arg region "$region" --slurpfile targets "$tmp/targets" \
  --arg digest "$(shasum -a 256 "$CLEANUP_POLICY" | awk '{print $1}')" \
  '{schema:1,environment:"uat",owner_repository:"ai-workspace-infra/iac_modules",owner_commit:$owner,
    run_id:$run,run_attempt:$attempt,project_id:$project,region:$region,policy_sha256:$digest,
    status:$status,accepted:($status == "verified-deletion"),targets:$targets[0],
    persistent_data_touched:false,images_pruned:false}' > "$receipt"
printf 'status=%s\nreceipt=%s\n' "$status" "$receipt" >> "$GITHUB_OUTPUT"
echo "UAT compute cleanup result: $status"
