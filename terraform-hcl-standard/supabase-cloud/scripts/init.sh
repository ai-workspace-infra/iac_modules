#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUPABASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GITOPS_ROOT="${GITOPS_ROOT:-$(cd "${SUPABASE_ROOT}/../.." && pwd)/gitops}"
RESOURCES="${RESOURCES:-${GITOPS_ROOT}/resources/svc.plus/dev/supabase/supabase.yaml}"
WORKDIR="${WORKDIR:-${SUPABASE_ROOT}/envs/dev}"

command -v terraform >/dev/null 2>&1 || {
  echo "terraform is required; install Terraform >= 1.5.0 first" >&2
  exit 1
}

echo "==> render Supabase declaration"
python3 "${SCRIPT_DIR}/render.py" render --resources "${RESOURCES}" --workdir "${WORKDIR}"

# Keep the direct URI in the process environment only. This accepts the
# declaration's URI environment variable without writing it to YAML or
# terraform.auto.tfvars.json.
URI_ENV="$(python3 "${SCRIPT_DIR}/render.py" uri-env --resources "${RESOURCES}")"
if [[ ! "${URI_ENV}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "invalid database.uri_env name: ${URI_ENV}" >&2
  exit 1
fi
if [[ -z "${TF_VAR_database_uri:-}" && -n "${!URI_ENV:-}" ]]; then
  export TF_VAR_database_uri="${!URI_ENV}"
fi

echo "==> terraform init"
terraform -chdir="${WORKDIR}" init -input=false

echo "==> Supabase Terraform workdir initialized"
echo "next: terraform -chdir=\"${WORKDIR}\" plan"
