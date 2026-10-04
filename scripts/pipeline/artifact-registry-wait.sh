#!/usr/bin/env bash
set -euo pipefail

# Wait for an immutable image tag to become readable before its consumer deploys.
# The exact tag is an acceptable readiness signal while a pushed multi-platform
# manifest is still being indexed and image_summary.digest is briefly empty.
: "${ARTIFACT_IMAGE_REPOSITORY:?ARTIFACT_IMAGE_REPOSITORY is required}"
: "${IMAGE_TAG:?IMAGE_TAG is required}"

attempts="${ARTIFACT_IMAGE_WAIT_ATTEMPTS:-30}"
interval_seconds="${ARTIFACT_IMAGE_WAIT_INTERVAL_SECONDS:-10}"
if [[ ! "${attempts}" =~ ^[1-9][0-9]*$ || ! "${interval_seconds}" =~ ^[1-9][0-9]*$ ]]; then
  echo 'ARTIFACT_IMAGE_WAIT_ATTEMPTS and ARTIFACT_IMAGE_WAIT_INTERVAL_SECONDS must be positive integers' >&2
  exit 2
fi

image_uri="${ARTIFACT_IMAGE_REPOSITORY}:${IMAGE_TAG}"
for ((attempt = 1; attempt <= attempts; attempt++)); do
  if digest="$(gcloud artifacts docker images describe "${image_uri}" --format='value(image_summary.digest)' 2>/dev/null)" && [[ -n "${digest}" ]]; then
    echo "Artifact Registry image is ready: ${image_uri} (${digest})"
    exit 0
  fi

  if tags="$(gcloud artifacts docker tags list "${ARTIFACT_IMAGE_REPOSITORY}" \
      --filter="tag:${IMAGE_TAG}" --format='value(tag)' 2>/dev/null)"; then
    while IFS= read -r tag; do
      if [[ "${tag}" == "${IMAGE_TAG}" ]]; then
        echo "Artifact Registry tag is ready: ${image_uri}"
        exit 0
      fi
    done <<< "${tags}"
  fi

  if (( attempt < attempts )); then
    echo "Waiting for Artifact Registry image (${attempt}/${attempts}): ${image_uri}"
    sleep "${interval_seconds}"
  fi
done

echo "Artifact Registry image did not become available before timeout: ${image_uri}" >&2
exit 1
