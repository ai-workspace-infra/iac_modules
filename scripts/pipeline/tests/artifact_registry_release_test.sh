#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
waiter="${root}/scripts/pipeline/artifact-registry-wait.sh"
promoter="${root}/scripts/pipeline/artifact-registry-promote.sh"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
mkdir -p "${work}/bin"

cat > "${work}/bin/gcloud" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${FAKE_GCLOUD_LOG}"
case "$*" in
  "artifacts docker images describe"*)
    [[ ! -f "${FAKE_TARGET_DIGEST}" ]] || cat "${FAKE_TARGET_DIGEST}"
    ;;
  "artifacts docker tags list"*)
    printf '%s\n' "${FAKE_TAGS:-}"
    ;;
  "container images add-tag"*)
    printf '%s\n' "${FAKE_COPY_DIGEST:-}" > "${FAKE_TARGET_DIGEST}"
    ;;
  *) exit 2 ;;
esac
FAKE
chmod +x "${work}/bin/gcloud"

export PATH="${work}/bin:${PATH}"
export FAKE_GCLOUD_LOG="${work}/gcloud.log"
export FAKE_TARGET_DIGEST="${work}/target-digest"
export ARTIFACT_IMAGE_REPOSITORY='asia-east1-docker.pkg.dev/example-uat/serverless/accounts'
export IMAGE_TAG='v2026.10.04-r1'
export ARTIFACT_IMAGE_WAIT_ATTEMPTS=1
export ARTIFACT_IMAGE_WAIT_INTERVAL_SECONDS=1
digest="sha256:$(printf 'a%.0s' {1..64})"
other="sha256:$(printf 'b%.0s' {1..64})"

printf '%s\n' "${digest}" > "${FAKE_TARGET_DIGEST}"
: > "${FAKE_GCLOUD_LOG}"
"${waiter}" > /dev/null
[[ "$(wc -l < "${FAKE_GCLOUD_LOG}")" -eq 1 ]]

rm "${FAKE_TARGET_DIGEST}"
export FAKE_TAGS="older ${IMAGE_TAG} unrelated"
! "${waiter}" > /dev/null 2>&1
export FAKE_TAGS="${IMAGE_TAG}"
"${waiter}" > /dev/null
export FAKE_TAGS=''
! "${waiter}" > /dev/null 2>&1
! ARTIFACT_IMAGE_WAIT_ATTEMPTS=0 "${waiter}" > /dev/null 2>&1

export SERVICE=accounts
export TARGET_IMAGE='asia-east1-docker.pkg.dev/example-prod/serverless/accounts'
export PROMOTION_MANIFEST
PROMOTION_MANIFEST="$(jq -nc --arg d "${digest}" --arg i "${ARTIFACT_IMAGE_REPOSITORY}" \
  '{images:[{service:"accounts", image:$i, digest:$d}]}' )"
export FAKE_COPY_DIGEST="${digest}"
export GITHUB_OUTPUT="${work}/outputs"
: > "${FAKE_GCLOUD_LOG}"
"${promoter}" > /dev/null
[[ "$(cat "${FAKE_TARGET_DIGEST}")" == "${digest}" ]]
[[ "$(cat "${GITHUB_OUTPUT}")" == "digest=${digest}" ]]
[[ "$(grep -c 'container images add-tag' "${FAKE_GCLOUD_LOG}")" == 1 ]]

: > "${FAKE_GCLOUD_LOG}"
"${promoter}" > /dev/null
! grep -q 'add-tag' "${FAKE_GCLOUD_LOG}"

printf '%s\n' "${other}" > "${FAKE_TARGET_DIGEST}"
: > "${FAKE_GCLOUD_LOG}"
! "${promoter}" > /dev/null 2>&1
! grep -q 'add-tag' "${FAKE_GCLOUD_LOG}"

rm "${FAKE_TARGET_DIGEST}"
export FAKE_COPY_DIGEST="${other}"
! "${promoter}" > /dev/null 2>&1

export PROMOTION_MANIFEST
PROMOTION_MANIFEST="$(jq -nc --arg d "${digest}" --arg i "${ARTIFACT_IMAGE_REPOSITORY}" \
  '{images:[{service:"accounts", image:$i, digest:$d},{service:"accounts", image:$i, digest:$d}]}' )"
: > "${FAKE_GCLOUD_LOG}"
! "${promoter}" > /dev/null 2>&1
! grep -q 'add-tag' "${FAKE_GCLOUD_LOG}"

echo 'artifact_registry_release_test: PASS'
