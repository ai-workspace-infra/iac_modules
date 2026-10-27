#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
release="${root}/scripts/pipeline/serverless-image-release.sh"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
mkdir -p "${work}/bin" "${work}/runner-temp"

cat > "${work}/bin/oras" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_ORAS_LOG"
case "$1" in
  login)
    [[ "${*: -1}" == --password-stdin ]]
    IFS= read -r _ || [[ -n "${_:-}" ]]
    ;;
  resolve)
    reference="${*: -1}"
    if [[ "$reference" == ghcr.io/ai-workspace-services/* ]]; then
      printf '%s\n' "${FAKE_SOURCE_TAG_DIGEST:-$FAKE_SOURCE_DIGEST}"
    elif [[ -f "$FAKE_TARGET_DIGEST" ]]; then
      cat "$FAKE_TARGET_DIGEST"
    else
      printf '%s\n' "${FAKE_RESOLVE_ERROR:-MANIFEST_UNKNOWN}" >&2
      exit 1
    fi
    ;;
  cp)
    source_reference="${*: -2:1}"
    [[ "$source_reference" == "$FAKE_EXPECTED_SOURCE_REFERENCE" ]]
    printf '%s\n' "$FAKE_SOURCE_DIGEST" > "$FAKE_TARGET_DIGEST"
    ;;
  *) exit 2 ;;
esac
FAKE
cat > "${work}/bin/gcloud" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
[[ "$*" == 'auth print-access-token' ]]
printf '%s\n' fake-gcp-access-token
FAKE
chmod 755 "${work}/bin/oras" "${work}/bin/gcloud"

export PATH="${work}/bin:${PATH}"
export ORAS_BIN="${work}/bin/oras"
export FAKE_ORAS_LOG="${work}/oras.log"
export FAKE_TARGET_DIGEST="${work}/target.digest"
FAKE_SOURCE_DIGEST="sha256:$(printf 'a%.0s' {1..64})"
export FAKE_SOURCE_DIGEST
export RUNNER_TEMP="${work}/runner-temp"
export GITOPS_ENVIRONMENT=uat
export GCP_PROJECT_ID=open-platform-uat
export GCP_REGION=asia-east1
export ARTIFACT_REGISTRY_ID=xwork-services
export SERVICE=accounts
export CANDIDATE_TAG=uat-daily-build-2026.10.27-r1
export GHCR_USERNAME=github-actions
export GHCR_TOKEN=fixture-only-token
export GITHUB_OUTPUT="${work}/outputs"
export SOURCE_MANIFEST="${work}/release.json"
source_sha=0123456789abcdef0123456789abcdef01234567
export FAKE_EXPECTED_SOURCE_REFERENCE="ghcr.io/ai-workspace-services/accounts@${FAKE_SOURCE_DIGEST}"
jq -n --arg sha "$source_sha" --arg digest "$FAKE_SOURCE_DIGEST" \
  '{schema_version:1,service:"accounts",source_sha:$sha,source_image:("ghcr.io/ai-workspace-services/accounts:sha-" + $sha),digest:$digest}' > "$SOURCE_MANIFEST"

run_release() {
  : > "$FAKE_ORAS_LOG"
  : > "$GITHUB_OUTPUT"
  env "$@" bash "$release"
}

run_release
target='asia-east1-docker.pkg.dev/open-platform-uat/xwork-services/accounts:uat-daily-build-2026.10.27-r1'
grep -Fxq "target_image=${target}" "$GITHUB_OUTPUT"
grep -Fxq "digest=${FAKE_SOURCE_DIGEST}" "$GITHUB_OUTPUT"
grep -Fxq "source_sha=${source_sha}" "$GITHUB_OUTPUT"
grep -Fq "cp --from-registry-config" "$FAKE_ORAS_LOG"
! grep -Eiq '(^|[[:space:]])docker([[:space:]]|$)' "$FAKE_ORAS_LOG"

# Retrying an exact candidate is idempotent; a different digest is never overwritten.
: > "$FAKE_ORAS_LOG"
run_release
! grep -Fq ' cp ' "$FAKE_ORAS_LOG"
printf '%s\n' "sha256:$(printf 'b%.0s' {1..64})" > "$FAKE_TARGET_DIGEST"
! run_release > /dev/null 2>&1
! grep -Fq ' cp ' "$FAKE_ORAS_LOG"

# Non-not-found registry errors fail closed instead of treating auth/network errors as an empty tag.
rm -f "$FAKE_TARGET_DIGEST"
! FAKE_RESOLVE_ERROR='unauthorized: permission denied' run_release > /dev/null 2>&1
! grep -Fq ' cp ' "$FAKE_ORAS_LOG"
unset FAKE_RESOLVE_ERROR
! FAKE_SOURCE_TAG_DIGEST="sha256:$(printf 'c%.0s' {1..64})" run_release > /dev/null 2>&1
! grep -Fq ' cp ' "$FAKE_ORAS_LOG"
unset FAKE_SOURCE_TAG_DIGEST

# Reject cross-environment, mutable, malformed, and cross-service inputs before registry access.
! GITOPS_ENVIRONMENT=prod run_release > /dev/null 2>&1
! CANDIDATE_TAG=latest run_release > /dev/null 2>&1
! SERVICE=unknown run_release > /dev/null 2>&1
jq '.digest="sha256:bad"' "$SOURCE_MANIFEST" > "${work}/bad.json"
! SOURCE_MANIFEST="${work}/bad.json" run_release > /dev/null 2>&1
jq '.source_image="ghcr.io/other-org/accounts:sha-0123456789abcdef0123456789abcdef01234567"' "$SOURCE_MANIFEST" > "${work}/foreign.json"
! SOURCE_MANIFEST="${work}/foreign.json" run_release > /dev/null 2>&1
! grep -Fq 'login ' "$FAKE_ORAS_LOG"

# content-service's owned package is named docs in GHCR; reject a guessed package name.
rm -f "$FAKE_TARGET_DIGEST"
export FAKE_EXPECTED_SOURCE_REFERENCE="ghcr.io/ai-workspace-services/docs@${FAKE_SOURCE_DIGEST}"
jq -n --arg sha "$source_sha" --arg digest "$FAKE_SOURCE_DIGEST" \
  '{schema_version:1,service:"content-service",source_sha:$sha,source_image:("ghcr.io/ai-workspace-services/docs:sha-" + $sha),digest:$digest}' > "${work}/content-service.json"
run_release SERVICE=content-service SOURCE_MANIFEST="${work}/content-service.json"
grep -Fxq "target_image=asia-east1-docker.pkg.dev/open-platform-uat/xwork-services/content-service:${CANDIDATE_TAG}" "$GITHUB_OUTPUT"
grep -Fq 'ghcr.io/ai-workspace-services/docs@sha256:' "$FAKE_ORAS_LOG"
jq '.source_image="ghcr.io/ai-workspace-services/content-service:sha-0123456789abcdef0123456789abcdef01234567"' \
  "${work}/content-service.json" > "${work}/content-service-wrong-package.json"
! run_release SERVICE=content-service SOURCE_MANIFEST="${work}/content-service-wrong-package.json" > /dev/null 2>&1
! grep -Fq 'login ' "$FAKE_ORAS_LOG"

echo 'serverless-image-release-test: PASS'
