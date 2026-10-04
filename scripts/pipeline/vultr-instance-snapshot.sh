#!/usr/bin/env bash
set -euo pipefail

# Create a Vultr instance snapshot, or resume waiting for an existing one.
# The caller owns approval and target selection; this executor owns provider I/O.
: "${VULTR_API_KEY:?VULTR_API_KEY is required}"
: "${INSTANCE_ID:?INSTANCE_ID is required}"

attempts="${VULTR_SNAPSHOT_WAIT_ATTEMPTS:-60}"
interval="${VULTR_SNAPSHOT_WAIT_INTERVAL_SECONDS:-30}"
[[ "${attempts}" =~ ^[1-9][0-9]*$ && "${interval}" =~ ^[0-9]+$ ]] || {
  echo 'Snapshot wait attempts must be positive and interval must be non-negative' >&2
  exit 2
}

api='https://api.vultr.com/v2/snapshots'
snapshot_id="${VULTR_SNAPSHOT_ID:-}"
if [[ -z "${snapshot_id}" ]]; then
  payload="$(jq -n --arg instance_id "${INSTANCE_ID}" '{instance_id: $instance_id}')"
  snapshot_id="$(curl -fsS --retry 3 -X POST \
    -H "Authorization: Bearer ${VULTR_API_KEY}" \
    -H 'Content-Type: application/json' \
    -d "${payload}" "${api}" | jq -r '.snapshot.id // empty')"
  [[ -n "${snapshot_id}" ]] || {
    echo '::error::Vultr did not return a snapshot ID' >&2
    exit 1
  }
fi

status=''
for ((attempt = 1; attempt <= attempts; attempt++)); do
  status="$(curl -fsS --retry 3 -H "Authorization: Bearer ${VULTR_API_KEY}" \
    "${api}/${snapshot_id}" | jq -r '.snapshot.status // empty')"
  echo "Snapshot ${snapshot_id}: ${status} (${attempt}/${attempts})"
  case "${status}" in
    complete) break ;;
    error) echo '::error::Vultr reported snapshot failure' >&2; exit 1 ;;
  esac
  if (( attempt < attempts )); then sleep "${interval}"; fi
done

[[ "${status}" == complete ]] || {
  echo '::error::Snapshot did not complete before timeout' >&2
  exit 1
}

printf 'snapshot_id=%s\n' "${snapshot_id}" >> "${GITHUB_OUTPUT:-/dev/stdout}"
