#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Apply GitHub Ruleset to protect release/* branches.

Usage:
  apply_ruleset.sh <owner/repo> [<owner/repo> ...]

Notes:
  - Requires: gh (authenticated), jq
  - Does NOT create/push branches or tags.
  - Ruleset payload is in: skills/release-branch-policy/references/ruleset.release-branches.json
EOF
}

if [[ $# -lt 1 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "missing: gh" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "missing: jq" >&2
  exit 1
fi

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PAYLOAD_FILE="${SKILL_DIR}/references/ruleset.release-branches.json"

if [[ ! -f "${PAYLOAD_FILE}" ]]; then
  echo "payload not found: ${PAYLOAD_FILE}" >&2
  exit 1
fi

NAME="$(jq -r '.name' < "${PAYLOAD_FILE}")"

for OWNER_REPO in "$@"; do
  echo ">>> ${OWNER_REPO}"

  # Find existing ruleset by name.
  existing_id="$(
    gh api "repos/${OWNER_REPO}/rulesets" --jq ".[] | select(.name == \"${NAME}\") | .id" 2>/dev/null || true
  )"

  if [[ -n "${existing_id}" ]]; then
    echo "Updating ruleset id=${existing_id}"
    gh api -X PUT "repos/${OWNER_REPO}/rulesets/${existing_id}" --input "${PAYLOAD_FILE}" >/dev/null
  else
    echo "Creating ruleset"
    gh api -H "Accept: application/vnd.github+json" -X POST "repos/${OWNER_REPO}/rulesets" --input "${PAYLOAD_FILE}" >/dev/null
  fi
done
