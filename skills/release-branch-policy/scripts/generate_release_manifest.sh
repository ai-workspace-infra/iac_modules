#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Generate a cross-repo release manifest (read-only) from local git state.

Usage:
  generate_release_manifest.sh <version> [--base <dir>] [--out <file>]

Examples:
  generate_release_manifest.sh v0.1
  generate_release_manifest.sh v0.1 --out releases/v0.1.yaml
  generate_release_manifest.sh v0.1 --base /Users/shenlan/workspaces/cloud-neutral-toolkit

Notes:
  - This script does NOT create/push branches or tags.
  - It inspects local refs only; if your local remotes are stale, run 'git fetch --all --tags' per repo first.
  - "Cross-repo association" is represented by this manifest file (repo -> release branch tip + tag tip).
EOF
}

if [[ $# -lt 1 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

VERSION="$1"
shift || true

BASE="/Users/shenlan/workspaces/cloud-neutral-toolkit"
OUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      BASE="${2:-}"
      shift 2
      ;;
    --out)
      OUT="${2:-}"
      shift 2
      ;;
    *)
      echo "unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${OUT}" ]]; then
  mkdir -p "releases"
  OUT="releases/${VERSION}.yaml"
fi

if [[ ! -d "${BASE}" ]]; then
  echo "missing base dir: ${BASE}" >&2
  exit 1
fi

REL_BRANCH="release/${VERSION}"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

{
  echo "version: ${VERSION}"
  echo "generated_at_utc: \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\""
  echo "base_dir: \"${BASE}\""
  echo "release_branch: \"${REL_BRANCH}\""
  echo "repos:"
} >"$tmp"

for d in "${BASE}"/*; do
  [[ -d "$d" ]] || continue
  [[ -d "$d/.git" ]] || continue

  name="$(basename "$d")"
  remote_url="$(cd "$d" && git config --get remote.origin.url 2>/dev/null || true)"

  rel_ref=""
  rel_sha=""
  if (cd "$d" && git show-ref --verify --quiet "refs/remotes/origin/${REL_BRANCH}"); then
    rel_ref="refs/remotes/origin/${REL_BRANCH}"
    rel_sha="$(cd "$d" && git rev-parse "refs/remotes/origin/${REL_BRANCH}")"
  elif (cd "$d" && git show-ref --verify --quiet "refs/heads/${REL_BRANCH}"); then
    rel_ref="refs/heads/${REL_BRANCH}"
    rel_sha="$(cd "$d" && git rev-parse "refs/heads/${REL_BRANCH}")"
  fi

  tag_sha=""
  if (cd "$d" && git show-ref --tags --quiet --verify "refs/tags/${VERSION}"); then
    tag_sha="$(cd "$d" && git rev-parse "${VERSION}^{}" 2>/dev/null || git rev-parse "${VERSION}" 2>/dev/null || true)"
  fi

  {
    echo "  - name: \"${name}\""
    echo "    path: \"${d}\""
    if [[ -n "${remote_url}" ]]; then
      echo "    remote: \"${remote_url}\""
    else
      echo "    remote: \"\""
    fi
    echo "    release:"
    echo "      branch: \"${REL_BRANCH}\""
    echo "      ref: \"${rel_ref}\""
    echo "      sha: \"${rel_sha}\""
    echo "    tag:"
    echo "      name: \"${VERSION}\""
    echo "      sha: \"${tag_sha}\""
  } >>"$tmp"
done

mv "$tmp" "$OUT"
echo "wrote: ${OUT}"
