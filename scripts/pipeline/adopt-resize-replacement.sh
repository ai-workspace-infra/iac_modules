#!/usr/bin/env bash
set -euo pipefail

: "${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE:?terraform workspace is required}"
: "${SOURCE_INSTANCE_ID:?source instance ID is required}"
: "${REPLACEMENT_INSTANCE_ID:?replacement instance ID is required}"

terraform workspace select "${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE}"

source_address=""
while IFS= read -r address; do
  [[ "${address}" == *"vultr_instance."* ]] || continue
  instance_id="$(terraform state show -no-color "${address}" 2>/dev/null \
    | sed -nE 's/^[[:space:]]*id[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' \
    | head -n 1)"
  if [[ "${instance_id}" == "${SOURCE_INSTANCE_ID}" ]]; then
    if [[ -n "${source_address}" ]]; then
      echo "::error::source instance appears at more than one Terraform address" >&2
      exit 1
    fi
    source_address="${address}"
  fi
done < <(terraform state list)

[[ -n "${source_address}" ]] || {
  echo "::error::source instance ${SOURCE_INSTANCE_ID} was not found in this workspace" >&2
  exit 1
}

# Keep an on-runner recovery copy before changing the remote state. Terraform's
# backend also versions this state, but this copy makes an interrupted adoption
# diagnosable without exposing the state as an artifact.
state_backup="${RUNNER_TEMP:-/tmp}/terraform-state-before-resize-${SOURCE_INSTANCE_ID}.json"
terraform state pull > "${state_backup}"

terraform state rm "${source_address}"
terraform import -input=false "${source_address}" "${REPLACEMENT_INSTANCE_ID}"

adopted_id="$(terraform state show -no-color "${source_address}" \
  | sed -nE 's/^[[:space:]]*id[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' \
  | head -n 1)"
[[ "${adopted_id}" == "${REPLACEMENT_INSTANCE_ID}" ]] || {
  echo "::error::replacement import verification failed" >&2
  exit 1
}

echo "Adopted replacement ${REPLACEMENT_INSTANCE_ID} at ${source_address}"
