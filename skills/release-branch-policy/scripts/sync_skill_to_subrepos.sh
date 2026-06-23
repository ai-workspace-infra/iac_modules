#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Copy this skill into all local Cloud-Neutral Toolkit sub-repos.

Usage:
  sync_skill_to_subrepos.sh

Copies:
  skills/release-branch-policy -> <repo>/skills/release-branch-policy

Notes:
  - Local path root: /Users/shenlan/workspaces/cloud-neutral-toolkit
  - Skips directories without .git
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

SRC_SKILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_REPO_ROOT="$(cd "${SRC_SKILL}/../.." && pwd)"

realpath_py() {
  python3 - "$1" <<'PY'
import os, sys
print(os.path.realpath(sys.argv[1]))
PY
}

BASE="/Users/shenlan/workspaces/cloud-neutral-toolkit"
if [[ ! -d "${BASE}" ]]; then
  echo "missing base dir: ${BASE}" >&2
  exit 1
fi

for d in "${BASE}"/*; do
  [[ -d "$d" ]] || continue
  [[ -d "$d/.git" ]] || continue

  # Don't delete our own source while syncing.
  if [[ "$(realpath_py "$d")" == "$(realpath_py "$SRC_REPO_ROOT")" ]]; then
    echo ">>> skipping source repo $d"
    continue
  fi

  mkdir -p "$d/skills"
  echo ">>> syncing to $d"
  rm -rf "$d/skills/release-branch-policy"
  cp -R "${SRC_SKILL}" "$d/skills/release-branch-policy"
done
