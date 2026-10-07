#!/usr/bin/env bash
set -euo pipefail

FRONTEND_ROUTER_DIR="${FRONTEND_ROUTER_DIR:?FRONTEND_ROUTER_DIR must point to a checked-out frontend-router repository}"
CONFIG_FILE="${CLOUDFLARE_BOUNDARY_CONFIG:?CLOUDFLARE_BOUNDARY_CONFIG must point to the rendered GitOps routing manifest}"
release_tag="${FRONTEND_ROUTER_RELEASE_TAG:?FRONTEND_ROUTER_RELEASE_TAG must identify a project CI release}"
[[ "$release_tag" =~ ^(uat-daily-build-|daily-build-|v)[0-9][0-9A-Za-z._-]*$ ]] || {
  echo 'Frontend Router CD accepts release tags only, never a floating branch.' >&2
  exit 2
}

test -d "${FRONTEND_ROUTER_DIR}"
test -f "${CONFIG_FILE}"
test -x "${FRONTEND_ROUTER_DIR}/scripts/deploy_from_gitops.sh"

release_dir="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/frontend-router-release.XXXXXX")"
release_repo='ai-workspace-services/frontend-router'
release_id="$(gh api "repos/${release_repo}/releases/tags/${release_tag}" --jq '.id // empty')"
[[ "$release_id" =~ ^[0-9]+$ ]] || {
  echo "Unable to resolve Frontend Router release ID for ${release_tag}." >&2
  exit 1
}

# The by-tag Release response can be stale immediately after publication and
# report an empty assets array. Resolve only the stable ID above, then list and
# download through the dedicated asset endpoints.
release_assets="$(gh api "repos/${release_repo}/releases/${release_id}/assets?per_page=100")"
for asset in frontend-router-worker.js release-metadata.json SHA256SUMS; do
  asset_id="$(jq -r --arg name "$asset" '[.[] | select(.name == $name)][0].id // empty' <<< "$release_assets")"
  [[ "$asset_id" =~ ^[0-9]+$ ]] || {
    echo "Required Frontend Router release asset is missing: ${asset}" >&2
    exit 1
  }
  curl --fail --location --silent --show-error --retry 3 \
    -H 'Accept: application/octet-stream' \
    -H "Authorization: Bearer ${GH_TOKEN:?GH_TOKEN must authorize release asset downloads}" \
    "https://api.github.com/repos/${release_repo}/releases/assets/${asset_id}" \
    --output "${release_dir}/${asset}"
done
# Check only the two explicit assets, never filenames supplied by an arbitrary
# checksum entry. Source identity must match the checked-out immutable tag.
awk '$2 == "frontend-router-worker.js" || $2 == "release-metadata.json" {print}' \
  "$release_dir/SHA256SUMS" > "$release_dir/verified-sums"
[[ "$(wc -l < "$release_dir/verified-sums" | tr -d ' ')" == 2 ]]
for asset in frontend-router-worker.js release-metadata.json; do
  [[ "$(awk -v name="$asset" '$2 == name {count++} END {print count+0}' "$release_dir/verified-sums")" == 1 ]]
done
(cd "$release_dir" && sha256sum -c verified-sums)
source_sha="$(git -C "$FRONTEND_ROUTER_DIR" rev-parse HEAD)"
jq -e --arg tag "$release_tag" --arg sha "$source_sha" \
  '.schema_version == 1 and .tag == $tag and .source_sha == $sha' \
  "$release_dir/release-metadata.json" >/dev/null
export FRONTEND_ROUTER_ARTIFACT_FILE="$release_dir/frontend-router-worker.js"
printf 'Deploying Frontend Router release %s at commit %s (prebuilt, no bundle).\n' "$release_tag" "$source_sha"

pushd "${FRONTEND_ROUTER_DIR}" >/dev/null
npm ci
FRONTEND_ROUTER_CONFIG_FILE="${CONFIG_FILE}" bash scripts/deploy_from_gitops.sh
popd >/dev/null
