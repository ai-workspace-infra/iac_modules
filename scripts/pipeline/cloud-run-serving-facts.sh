#!/usr/bin/env bash
# Query Cloud Run and OCI registry facts. The Toolkit caller owns the expected
# digest comparison and final delivery gate.
set -euo pipefail

: "${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
: "${GCP_REGION:?GCP_REGION is required}"
: "${CLOUD_RUN_SERVICE_NAME:?CLOUD_RUN_SERVICE_NAME is required}"
: "${ARTIFACT_DIGEST:?ARTIFACT_DIGEST is required}"
: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"

[[ "${ARTIFACT_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo '::error::ARTIFACT_DIGEST must be sha256.' >&2
  exit 1
}

child=""
if [[ -n "${IMAGE:-}" ]]; then
  registry="${IMAGE%%/*}"
  repository="${IMAGE#*/}"
  [[ "${registry}" =~ ^[a-z0-9][a-z0-9-]*-docker[.]pkg[.]dev$ && "${repository}" != "${IMAGE}" && \
    "${repository}" =~ ^[a-z0-9][a-z0-9._/-]*[a-z0-9]$ && \
    "${repository}" != *..* && "${repository}" != *//* ]] || {
    echo '::error::IMAGE must be an Artifact Registry repository path without a tag or digest.' >&2
    exit 1
  }
  access_token="$(gcloud auth print-access-token)"
  [[ -n "${access_token}" ]] || {
    echo '::error::cannot mint an access token for the Artifact Registry metadata query.' >&2
    exit 1
  }
  raw="$(printf 'Authorization: Bearer %s\n' "${access_token}" | curl --fail --silent --show-error --connect-timeout 10 --max-time 60 \
    --header @- \
    --header 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
    "https://${registry}/v2/${repository}/manifests/${ARTIFACT_DIGEST}")" || {
    echo "::error::cannot read ${IMAGE}@${ARTIFACT_DIGEST} from the registry." >&2
    exit 1
  }
  unset access_token
  child="$(jq -er '
    if has("manifests") then
      [.manifests[]? | select(.platform.os == "linux" and .platform.architecture == "amd64") | .digest]
      | if length == 1 then .[0] elif length == 0 then "" else error("several linux/amd64 manifests") end
    else "" end
  ' <<<"${raw}")" || {
    echo "::error::${IMAGE}@${ARTIFACT_DIGEST} has an ambiguous linux/amd64 manifest." >&2
    exit 1
  }
  [[ -z "${child}" || "${child}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    echo '::error::the linux/amd64 manifest digest is malformed.' >&2
    exit 1
  }
fi

service="$(gcloud run services describe "${CLOUD_RUN_SERVICE_NAME}" \
  --project="${GCP_PROJECT_ID}" --region="${GCP_REGION}" --format=json)"
revision="$(jq -er '.status.latestReadyRevisionName | select(type == "string" and length > 0)' <<<"${service}")" || {
  echo "::error::${CLOUD_RUN_SERVICE_NAME} has no ready revision." >&2
  exit 1
}
traffic="$(jq -c --arg revision "${revision}" \
  '[.status.traffic[]? | select((.percent // 0) > 0) | (.revisionName // $revision)] | unique' <<<"${service}")"
image="$(gcloud run revisions describe "${revision}" \
  --project="${GCP_PROJECT_ID}" --region="${GCP_REGION}" --format='value(status.imageDigest)')"
serving_digest="${image##*@}"
[[ "${image}" == *@sha256:* && "${serving_digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "::error::${CLOUD_RUN_SERVICE_NAME} ready revision returned a malformed image digest." >&2
  exit 1
}

{
  echo "latest_ready_revision=${revision}"
  echo "traffic_revisions=${traffic}"
  echo "serving_digest=${serving_digest}"
  echo "linux_amd64_child_digest=${child}"
} >> "${GITHUB_OUTPUT}"
echo "Read Cloud Run serving facts for ${CLOUD_RUN_SERVICE_NAME}; final digest acceptance remains with the caller."
