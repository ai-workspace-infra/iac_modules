#!/usr/bin/env bash
set -euo pipefail

: "${GITOPS_ENVIRONMENT:?GITOPS_ENVIRONMENT is required}"
: "${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
: "${GCP_REGION:?GCP_REGION is required}"
: "${ARTIFACT_REGISTRY_ID:?ARTIFACT_REGISTRY_ID is required}"
: "${SOURCE_MANIFEST:?SOURCE_MANIFEST is required}"
: "${SERVICE:?SERVICE is required}"
: "${CANDIDATE_TAG:?CANDIDATE_TAG is required}"
: "${GHCR_USERNAME:?GHCR_USERNAME is required}"
: "${GHCR_TOKEN:?GHCR_TOKEN is required}"
ORAS_BIN="${ORAS_BIN:-$(command -v oras || true)}"

[[ "${GITOPS_ENVIRONMENT}" == uat ]] || {
  echo '::error::serverless-image-release is restricted to the GitOps UAT target.' >&2
  exit 2
}
[[ "${SERVICE}" =~ ^(accounts|content-service|billing-service)$ ]] || {
  echo '::error::service is not an allowlisted UAT Cloud Run service.' >&2
  exit 2
}
case "${SERVICE}" in
  accounts) source_package=accounts ;;
  billing-service) source_package=billing-service ;;
  content-service) source_package=docs ;;
esac
[[ "${GCP_PROJECT_ID}" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ &&
   "${GCP_REGION}" =~ ^[a-z]+-[a-z]+[0-9]+$ &&
   "${ARTIFACT_REGISTRY_ID}" =~ ^[a-z][a-z0-9-]{0,62}$ ]] || {
  echo '::error::the resolved GitOps GCP target is malformed.' >&2
  exit 2
}
[[ "${CANDIDATE_TAG}" =~ ^(uat-)?daily-build-[0-9]{4}\.[0-9]{2}\.[0-9]{2}-r[1-9][0-9]*$ ]] || {
  echo '::error::candidate_tag must be an immutable daily-build release tag.' >&2
  exit 2
}
[[ -n "${ORAS_BIN}" && -x "${ORAS_BIN}" ]] || {
  echo '::error::a pinned ORAS CLI binary is required.' >&2
  exit 2
}

manifest_service="$(jq -er '.service | strings' "${SOURCE_MANIFEST}")" || {
  echo '::error::service release manifest is invalid.' >&2
  exit 2
}
source_sha="$(jq -er '.source_sha | strings' "${SOURCE_MANIFEST}")" || {
  echo '::error::service release manifest is missing source_sha.' >&2
  exit 2
}
source_image="$(jq -er '.source_image | strings' "${SOURCE_MANIFEST}")" || {
  echo '::error::service release manifest is missing source_image.' >&2
  exit 2
}
source_digest="$(jq -er '.digest | strings' "${SOURCE_MANIFEST}")" || {
  echo '::error::service release manifest is missing digest.' >&2
  exit 2
}
[[ "$(jq -r '.schema_version // empty' "${SOURCE_MANIFEST}")" == 1 &&
   "${manifest_service}" == "${SERVICE}" &&
   "${source_sha}" =~ ^[0-9a-f]{40}$ &&
   "${source_image}" == "ghcr.io/ai-workspace-services/${source_package}:sha-${source_sha}" &&
   "${source_digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo '::error::service release manifest must bind the allowlisted service, source SHA tag, GHCR image and immutable digest.' >&2
  exit 2
}

target_repository="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${ARTIFACT_REGISTRY_ID}/${SERVICE}"
target_image="${target_repository}:${CANDIDATE_TAG}"
source_repository="${source_image%:*}"
source_reference="${source_repository}@${source_digest}"
auth_dir="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/serverless-image-auth.XXXXXX")"
auth_file="${auth_dir}/registry-auth.json"
chmod 700 "${auth_dir}"
trap 'rm -rf "${auth_dir}"' EXIT

printf '%s\n' "${GHCR_TOKEN}" | "${ORAS_BIN:-oras}" login ghcr.io \
  --registry-config "${auth_file}" --username "${GHCR_USERNAME}" --password-stdin >/dev/null
gcloud_token="$(gcloud auth print-access-token)"
[[ -n "${gcloud_token}" ]] || {
  echo '::error::Google identity returned no Artifact Registry access token.' >&2
  exit 1
}
printf '%s\n' "${gcloud_token}" | "${ORAS_BIN:-oras}" login "${GCP_REGION}-docker.pkg.dev" \
  --registry-config "${auth_file}" --username oauth2accesstoken --password-stdin >/dev/null
unset GHCR_TOKEN gcloud_token

source_tag_digest="$("${ORAS_BIN:-oras}" resolve --registry-config "${auth_file}" "${source_image}")" || {
  echo '::error::the source SHA tag could not be resolved from GHCR.' >&2
  exit 1
}
[[ "${source_tag_digest}" == "${source_digest}" ]] || {
  echo '::error::the GHCR SHA tag does not resolve to the digest in the service release manifest.' >&2
  exit 1
}

if existing_digest="$("${ORAS_BIN:-oras}" resolve --registry-config "${auth_file}" "${target_image}" 2>"${auth_dir}/resolve.err")"; then
  [[ "${existing_digest}" == "${source_digest}" ]] || {
    echo '::error::candidate tag is already bound to a different Artifact Registry digest; refusing overwrite.' >&2
    exit 1
  }
else
  if ! grep -Eiq 'MANIFEST_UNKNOWN|NAME_UNKNOWN|manifest unknown|not found' "${auth_dir}/resolve.err"; then
    echo '::error::could not safely determine whether the Artifact Registry candidate tag exists.' >&2
    exit 1
  fi
  "${ORAS_BIN:-oras}" cp --from-registry-config "${auth_file}" --to-registry-config "${auth_file}" \
    "${source_reference}" "${target_image}"
fi

verified_digest="$("${ORAS_BIN:-oras}" resolve --registry-config "${auth_file}" "${target_image}")" || {
  echo '::error::Artifact Registry readback failed after OCI copy.' >&2
  exit 1
}
[[ "${verified_digest}" == "${source_digest}" ]] || {
  echo '::error::Artifact Registry readback digest does not match the GHCR source digest.' >&2
  exit 1
}

printf 'target_image=%s\ndigest=%s\nsource_sha=%s\n' \
  "${target_image}" "${source_digest}" "${source_sha}" >> "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
echo "Published ${SERVICE} candidate from source SHA ${source_sha}; verified digest ${source_digest}."
