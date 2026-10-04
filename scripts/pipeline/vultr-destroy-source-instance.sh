#!/usr/bin/env bash
set -euo pipefail

# Irreversible provider operation. The control plane must complete snapshot,
# replacement health check, DNS cutover and observation before invoking this.
: "${VULTR_API_KEY:?VULTR_API_KEY is required}"
: "${INSTANCE_ID:?INSTANCE_ID is required}"
: "${REPLACEMENT_IP:?REPLACEMENT_IP is required}"
[[ "${CONFIRM_DESTROY:-false}" == true ]] || {
  echo '::error::CONFIRM_DESTROY=true is required' >&2
  exit 1
}

echo "Deleting source instance ${INSTANCE_ID} after approved cutover; replacement=${REPLACEMENT_IP}"
curl -fsS --retry 3 -X DELETE \
  -H "Authorization: Bearer ${VULTR_API_KEY}" \
  "https://api.vultr.com/v2/instances/${INSTANCE_ID}"
