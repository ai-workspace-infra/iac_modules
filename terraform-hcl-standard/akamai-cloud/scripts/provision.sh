#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GITOPS_ROOT="${GITOPS_ROOT:-$(cd "${ROOT}/../.." && pwd)/gitops}"
IAC_NAMESPACE="${IAC_NAMESPACE:?set IAC_NAMESPACE to one isolated Akamai namespace}"
RESOURCES="${RESOURCES:-${GITOPS_ROOT}/resources/svc.plus/uat/akamai/${IAC_NAMESPACE}.yaml}"
WORKDIR="${WORKDIR:-${ROOT}/envs/uat/${IAC_NAMESPACE}}"

python3 "${SCRIPT_DIR}/generate.py" render \
  --resources "${RESOURCES}" \
  --workdir "${WORKDIR}" \
  --namespace "${IAC_NAMESPACE}"
terraform -chdir="${WORKDIR}" init -input=false
terraform -chdir="${WORKDIR}" apply -input=false
python3 "${SCRIPT_DIR}/generate.py" inventory --resources "${RESOURCES}" --workdir "${WORKDIR}"
