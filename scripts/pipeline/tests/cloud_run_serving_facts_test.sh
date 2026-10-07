#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
script="${root}/scripts/pipeline/cloud-run-serving-facts.sh"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
mkdir -p "${work}/bin"

cat > "${work}/bin/curl" <<'FAKE'
#!/usr/bin/env bash
[[ "$(cat)" == "Authorization: Bearer test-access-token" ]] || exit 8
[[ "$*" == *"https://asia-northeast1-docker.pkg.dev/v2/open-platform-uat/serverless/accounts/manifests/sha256:"* ]] || exit 9
case "${FAKE_IMAGE_KIND:-index}" in
  index) jq -n --arg child "sha256:$(printf 'b%.0s' {1..64})" '{manifests:[{platform:{os:"linux",architecture:"amd64"},digest:$child},{platform:{os:"unknown",architecture:"unknown"},digest:"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"}]}' ;;
  single) echo '{"schemaVersion":2,"mediaType":"application/vnd.oci.image.manifest.v1+json"}' ;;
  ambiguous) jq -n --arg a "sha256:$(printf 'b%.0s' {1..64})" --arg b "sha256:$(printf 'd%.0s' {1..64})" '{manifests:[{platform:{os:"linux",architecture:"amd64"},digest:$a},{platform:{os:"linux",architecture:"amd64"},digest:$b}]}' ;;
esac
FAKE
cat > "${work}/bin/gcloud" <<'FAKE'
#!/usr/bin/env bash
case "$*" in
  "auth print-access-token") printf '%s\n' 'test-access-token' ;;
  "run services describe "*) printf '%s\n' "${FAKE_SERVICE_JSON}" ;;
  "run revisions describe "*) printf '%s\n' "${FAKE_IMAGE}" ;;
  *) exit 9 ;;
esac
FAKE
chmod +x "${work}/bin/"*

digest="sha256:$(printf 'a%.0s' {1..64})"
child="sha256:$(printf 'b%.0s' {1..64})"
service='{"status":{"latestReadyRevisionName":"accounts-00042","traffic":[{"revisionName":"accounts-00042","percent":90},{"revisionName":"accounts-00041","percent":10}]}}'
run() {
  : > "${work}/output"
  env PATH="${work}/bin:${PATH}" GCP_PROJECT_ID=open-platform-uat GCP_REGION=asia-northeast1 \
    CLOUD_RUN_SERVICE_NAME=uat-accounts IMAGE=asia-northeast1-docker.pkg.dev/open-platform-uat/serverless/accounts \
    ARTIFACT_DIGEST="${digest}" GITHUB_OUTPUT="${work}/output" FAKE_SERVICE_JSON="${service}" \
    FAKE_IMAGE="asia-northeast1-docker.pkg.dev/open-platform-uat/serverless/accounts@${child}" "$@" \
    bash "${script}" > "${work}/stdout" 2> "${work}/stderr"
}

run
grep -Fqx 'latest_ready_revision=accounts-00042' "${work}/output"
grep -Fqx 'traffic_revisions=["accounts-00041","accounts-00042"]' "${work}/output"
grep -Fqx "serving_digest=${child}" "${work}/output"
grep -Fqx "linux_amd64_child_digest=${child}" "${work}/output"

run FAKE_IMAGE_KIND=single
grep -Fqx 'linux_amd64_child_digest=' "${work}/output"
run FAKE_IMAGE_KIND=ambiguous && { echo 'ambiguous linux/amd64 index must fail' >&2; exit 1; }
grep -q 'ambiguous linux/amd64 manifest' "${work}/stderr"

run IMAGE=accounts:latest && { echo 'tagged image path must fail' >&2; exit 1; }
grep -q 'Artifact Registry repository path' "${work}/stderr"

echo 'cloud_run_serving_facts_test: PASS'
