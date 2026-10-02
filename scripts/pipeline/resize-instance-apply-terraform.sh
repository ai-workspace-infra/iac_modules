#!/usr/bin/env bash
set -euo pipefail

: "${IAC_ROOT:?IAC_ROOT is required}"
: "${OPERATION_ID:?OPERATION_ID is required}"
: "${DIRECTION:?DIRECTION is required}"
: "${TARGET_PLAN:?TARGET_PLAN is required}"
: "${INSTANCE_ID:?INSTANCE_ID is required}"
: "${REGION:?REGION is required}"
: "${LABEL:?LABEL is required}"
: "${OS_ID:?OS_ID is required}"

workdir="${RUNNER_TEMP}/resize-instance-${OPERATION_ID}"
mkdir -p "${workdir}"

if [[ "${DIRECTION}" == upgrade ]]; then
  cat > "${workdir}/main.tf" <<'HCL'
terraform {
  required_providers {
    vultr = { source = "vultr/vultr", version = "~> 2.19" }
  }
}

provider "vultr" {}

resource "vultr_instance" "target" {
  label       = var.label
  region      = var.region
  plan        = var.target_plan
  os_id       = var.os_id
  enable_ipv6 = true
  backups     = "enabled"
}

variable "label" { type = string }
variable "region" { type = string }
variable "target_plan" { type = string }
variable "os_id" { type = number }
HCL
  cat > "${workdir}/terraform.tfvars" <<EOF
label = "${LABEL}"
region = "${REGION}"
target_plan = "${TARGET_PLAN}"
os_id = ${OS_ID}
EOF
  terraform -chdir="${workdir}" init -input=false
  terraform -chdir="${workdir}" import -input=false vultr_instance.target "${INSTANCE_ID}"
else
  : "${SNAPSHOT_ID:?SNAPSHOT_ID is required for downgrade}"
  cat > "${workdir}/main.tf" <<HCL
terraform {
  required_providers {
    vultr = { source = "vultr/vultr", version = "~> 2.19" }
  }
}

provider "vultr" {}

module "replacement" {
  source       = "${IAC_ROOT}/terraform-hcl-standard/vultr-vps/modules/resize-instance"
  label        = "${LABEL}-replacement"
  region       = "${REGION}"
  target_plan  = "${TARGET_PLAN}"
  snapshot_id  = "${SNAPSHOT_ID}"
  operation_id = "${OPERATION_ID}"
}

output "instance_id" { value = module.replacement.instance_id }
output "main_ip" { value = module.replacement.main_ip }
HCL
  terraform -chdir="${workdir}" init -input=false
fi

terraform -chdir="${workdir}" plan -input=false -out=tfplan
terraform -chdir="${workdir}" show -json tfplan > "${workdir}/tfplan.json"

if [[ "${DIRECTION}" == downgrade ]]; then
  additions="$(jq '[.resource_changes[]? | select(.change.actions == ["create"])] | length' "${workdir}/tfplan.json")"
  destroys="$(jq '[.resource_changes[]? | select(.change.actions | index("delete"))] | length' "${workdir}/tfplan.json")"
  [[ "${additions}" == 1 && "${destroys}" == 0 ]] || {
    echo "::error::Replacement plan must be exactly 1 create and 0 destroys" >&2
    exit 1
  }
fi

terraform -chdir="${workdir}" apply -input=false -auto-approve tfplan

if [[ "${DIRECTION}" == downgrade ]]; then
  echo "replacement_id=$(terraform -chdir="${workdir}" output -raw instance_id)" >> "${GITHUB_OUTPUT:-/dev/stdout}"
  echo "replacement_ip=$(terraform -chdir="${workdir}" output -raw main_ip)" >> "${GITHUB_OUTPUT:-/dev/stdout}"
fi
