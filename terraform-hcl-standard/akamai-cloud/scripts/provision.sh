#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GITOPS_ROOT="${GITOPS_ROOT:-$(cd "${ROOT}/../.." && pwd)/gitops}"
RESOURCES="${RESOURCES:-${GITOPS_ROOT}/resources/svc.plus/uat/akamai/ai-workspace.yaml}"
WORKDIR="${WORKDIR:-${ROOT}/envs/uat}"

python3 "${SCRIPT_DIR}/generate.py" render --resources "${RESOURCES}" --workdir "${WORKDIR}"
terraform -chdir="${WORKDIR}" init -input=false
terraform -chdir="${WORKDIR}" apply -input=false
python3 "${SCRIPT_DIR}/generate.py" inventory --resources "${RESOURCES}" --workdir "${WORKDIR}"
