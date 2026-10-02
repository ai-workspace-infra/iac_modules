#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
script="${root_dir}/scripts/pipeline/ensure-gcp-vm-running.py"

test -x "${script}" || { echo "runtime reconciliation script must be executable" >&2; exit 1; }
grep -Fq 'instances", "start"' "${script}"
grep -Fq 'never creates, replaces, or deletes' "${script}"

echo 'GCP runtime reconciliation contract passed.'
