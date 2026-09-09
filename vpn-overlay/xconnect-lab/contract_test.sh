#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
main="${root}/main.tf"

terraform -chdir="${root}" fmt -check
[[ $(grep -Fc 'resource "aws_instance"' "${main}") -eq 2 ]]
[[ $(grep -Fc 'resource "aws_security_group"' "${main}") -eq 2 ]]

for forbidden in aws_vpc aws_subnet aws_internet_gateway aws_route_table aws_route_table_association aws_key_pair; do
  if grep -Fq "resource \"${forbidden}\"" "${main}"; then
    echo "UAT lab must reuse existing networking; forbidden resource: ${forbidden}" >&2
    exit 1
  fi
done

for forbidden in aws_iam_role aws_iam_instance_profile aws_iam_policy; do
  if grep -Fq "resource \"${forbidden}\"" "${main}"; then
    echo "UAT lab must not create IAM resources; forbidden resource: ${forbidden}" >&2
    exit 1
  fi
done

grep -Fq 'data "aws_vpc" "uat"' "${main}"
if grep -Fq 'subnet_id' "${main}"; then
  echo 'Ephemeral Spot nodes must let EC2 select a default subnet/AZ with capacity.' >&2
  exit 1
fi
grep -Fq 'var.aws_client_instance_type == "t4g.micro"' "${main}"
grep -Fq 'var.aws_gateway_instance_type == "t4g.small"' "${main}"
grep -Fq 'variable "gateway_transport_ingress_cidrs"' "${main}"
grep -Fq 'can(formatdate(' "${main}"
grep -Fq 'type     = list(string)' "${main}"
grep -Fq 'default  = []' "${main}"
grep -Fq 'length(var.gateway_transport_ingress_cidrs) <= 2' "${main}"
grep -Fq 'length(distinct(var.gateway_transport_ingress_cidrs))' "${main}"
grep -Fq 'try(' "${main}"
grep -Fq 'can(cidrnetmask(cidr))' "${main}"
grep -Fq 'cidr == format("%s/32", cidrhost(cidr, 0))' "${main}"
grep -Fq 'dynamic "ingress"' "${main}"
grep -Fq 'for_each = var.gateway_transport_ingress_cidrs' "${main}"
grep -Fq 'cidr_blocks = [ingress.value]' "${main}"
grep -Fq 'local.gateway_transport_access_enabled ? aws_instance.gateway.public_ip : aws_instance.gateway.private_ip' "${main}"
grep -Fq 'output "gateway_transport_access_enabled"' "${main}"
[[ $(grep -Ec 'from_port[[:space:]]+= 443' "${main}") -eq 2 ]]
# The SSH debug rule is also a dynamic ingress block. Select the transport block
# by its dedicated iterator instead of relying on declaration order.
desktop_ingress=$(awk '
  /dynamic "ingress"/ { inside = 1; wanted = 0; block = "" }
  inside { block = block $0 ORS }
  inside && /for_each = var.gateway_transport_ingress_cidrs/ { wanted = 1 }
  inside && /^  }$/ {
    if (wanted) { printf "%s", block; exit }
    inside = 0
  }
' "${main}")
grep -Eq 'from_port[[:space:]]+= 443' <<<"${desktop_ingress}"
grep -Eq 'to_port[[:space:]]+= 443' <<<"${desktop_ingress}"
grep -Eq 'protocol[[:space:]]+= "tcp"' <<<"${desktop_ingress}"
if grep -Eq 'from_port.*(22|8443)|to_port.*(22|8443)|protocol.*udp' <<<"${desktop_ingress}"; then
  echo 'Gateway transport ingress must be limited to TCP 443.' >&2
  exit 1
fi
if grep -Fq 'protocol    = "udp"' "${main}"; then
  echo 'Gateway transport ingress must not open UDP.' >&2
  exit 1
fi
[[ $(grep -Fc 'market_type = "spot"' "${main}") -eq 2 ]]
[[ $(grep -Fc 'spot_instance_type             = "one-time"' "${main}") -eq 2 ]]
[[ $(grep -Fc 'instance_interruption_behavior = "terminate"' "${main}") -eq 2 ]]
[[ $(grep -Fc 'timeouts { create = "5m" }' "${main}") -eq 2 ]]
[[ $(grep -Fc 'instance_initiated_shutdown_behavior' "${main}") -eq 0 ]]
[[ $(grep -Fc 'expires_at     = var.expires_at' "${main}") -eq 2 ]]
grep -Fq 'OnCalendar=$${expiry_calendar}' "${root}/bootstrap.sh"
grep -Fq "'+%Y-%m-%d %H:%M:%S UTC'" "${root}/bootstrap.sh"
grep -Fq 'AccuracySec=1s' "${root}/bootstrap.sh"
grep -Fq 'Persistent=true' "${root}/bootstrap.sh"
grep -Fq 'ExecStart=/sbin/poweroff' "${root}/bootstrap.sh"
grep -Fq 'expires_at must be absolute RFC3339 UTC' "${root}/bootstrap.sh"
grep -Fq 'Environment = "uat"' "${main}"
grep -Fq "'\${ssh_public_key}'" "${root}/bootstrap.sh"

bash "${root}/expiry_timer_test.sh"

echo 'XConnect UAT IaC contract creates two ARM64 Spot nodes and reuses the UAT network.'
