#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${RESOURCES:?explicit nonsecret YAML required}"
: "${WORKDIR:?fresh isolated output directory required}"
python3 "${SCRIPT_DIR}/render_contract.py" render --resources "${RESOURCES}" --workdir "${WORKDIR}"
echo "Offline render complete. Terraform init/plan/apply are separate controlled operations."
