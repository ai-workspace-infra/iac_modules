#!/usr/bin/env bash
set -euo pipefail

# Copy the digest accepted by UAT into the target repository without rebuilding.
# The caller validates the UAT release manifest before passing it here.
: "${PROMOTION_MANIFEST:?PROMOTION_MANIFEST is required}"
: "${SERVICE:?SERVICE is required}"
: "${TARGET_IMAGE:?TARGET_IMAGE is required}"
: "${IMAGE_TAG:?IMAGE_TAG is required}"

entries="$(jq -c --arg service "${SERVICE}" '[.images[] | select(.service == $service)]' <<< "${PROMOTION_MANIFEST}")" || {
  echo "::error::${SERVICE}: invalid promotion manifest." >&2
  exit 1
}
[[ "$(jq 'length' <<< "${entries}")" == 1 ]] || {
  echo "::error::${SERVICE}: expected exactly one accepted UAT image." >&2
  exit 1
}
source_image="$(jq -r '.[0].image // empty' <<< "${entries}")"
digest="$(jq -r '.[0].digest // empty' <<< "${entries}")"
[[ -n "${source_image}" && "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "::error::${SERVICE}: missing source image or invalid sha256 digest." >&2
  exit 1
}

image_digest() {
  gcloud artifacts docker images describe "$1" --format='value(image_summary.digest)' 2>/dev/null || true
}

existing="$(image_digest "${TARGET_IMAGE}:${IMAGE_TAG}")"
if [[ -n "${existing}" && "${existing}" != "${digest}" ]]; then
  echo "::error::${SERVICE}: release tag is already bound to a different digest; refusing overwrite." >&2
  exit 1
fi
if [[ -z "${existing}" ]]; then
  gcloud container images add-tag "${source_image}@${digest}" "${TARGET_IMAGE}:${IMAGE_TAG}" --quiet
fi

promoted="$(image_digest "${TARGET_IMAGE}:${IMAGE_TAG}")"
[[ "${promoted}" == "${digest}" ]] || {
  echo "::error::${SERVICE}: promoted tag does not resolve to the UAT digest." >&2
  exit 1
}
echo "${SERVICE}: ${TARGET_IMAGE}:${IMAGE_TAG} is the UAT-accepted ${digest}."
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  printf 'digest=%s\n' "${digest}" >> "${GITHUB_OUTPUT}"
fi
