terraform {
  required_version = ">= 1.9.5, < 2.0.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {}
}

variable "run_id" {
  type = string
  validation {
    condition     = can(regex("^xcl-[0-9]+-[0-9]+$", var.run_id))
    error_message = "Use xcl-GITHUB_RUN_ID-GITHUB_RUN_ATTEMPT, never an environment name."
  }
}

variable "expires_at" {
  type = string
  validation {
    condition = can(formatdate("YYYY-MM-DD hh:mm:ss ZZZ", var.expires_at)) && can(
      regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", var.expires_at)
    )
    error_message = "expires_at must be an absolute RFC3339 UTC timestamp ending in Z."
  }
}

variable "runner_cidr" {
  type = string
  validation {
    condition     = can(cidrnetmask(var.runner_cidr)) && endswith(var.runner_cidr, "/32")
    error_message = "Runner access must be one IPv4 /32."
  }
}

variable "ssh_debug_ingress_cidrs" {
  type     = list(string)
  default  = []
  nullable = true
  validation {
    condition = try(
      var.ssh_debug_ingress_cidrs != null &&
      length(var.ssh_debug_ingress_cidrs) <= 2 &&
      length(distinct(var.ssh_debug_ingress_cidrs)) == length(var.ssh_debug_ingress_cidrs) &&
      alltrue([
        for cidr in var.ssh_debug_ingress_cidrs : try(
          can(cidrnetmask(cidr)) &&
          cidr != "" &&
          cidr != "0.0.0.0/0" &&
          cidr == trimspace(cidr) &&
          cidr == format("%s/32", cidrhost(cidr, 0)),
          false
        )
      ]),
      false
    )
    error_message = "ssh_debug_ingress_cidrs must contain at most two unique canonical IPv4 /32 CIDRs."
  }
}

variable "gateway_transport_ingress_cidrs" {
  type     = list(string)
  default  = []
  nullable = true
  validation {
    condition = try(
      var.gateway_transport_ingress_cidrs != null &&
      length(var.gateway_transport_ingress_cidrs) <= 2 &&
      length(distinct(var.gateway_transport_ingress_cidrs)) == length(var.gateway_transport_ingress_cidrs) &&
      alltrue([
        for cidr in var.gateway_transport_ingress_cidrs : try(
          can(cidrnetmask(cidr)) &&
          cidr != "" &&
          cidr != "0.0.0.0/0" &&
          cidr == trimspace(cidr) &&
          cidr == format("%s/32", cidrhost(cidr, 0)),
          false
        )
      ]),
      false
    )
    error_message = "gateway_transport_ingress_cidrs must contain at most two unique canonical IPv4 /32 CIDRs."
  }
}

variable "ssh_public_key" { type = string }
variable "aws_region" { type = string }
variable "aws_client_instance_type" {
  type = string
  validation {
    condition     = var.aws_client_instance_type == "t4g.micro"
    error_message = "The UAT controlled-client must be t4g.micro (2 vCPU / 1 GiB)."
  }
}

variable "aws_gateway_instance_type" {
  type = string
  validation {
    condition     = var.aws_gateway_instance_type == "t4g.small"
    error_message = "The UAT Gateway must be t4g.small (2 vCPU / 2 GiB)."
  }
}
variable "aws_ami" { type = string }

variable "gateway_provider" {
  type    = string
  default = "aws-spot"
  validation {
    condition     = var.gateway_provider == "aws-spot"
    error_message = "The UAT validation module only accepts aws-spot."
  }
}

variable "zero_accounts_api_url" {
  type = string
  validation {
    condition     = can(regex("^https://", var.zero_accounts_api_url))
    error_message = "zero_accounts_api_url must be an HTTPS XConnect Zero accounts API URL."
  }
}

variable "zero_portal_url" {
  type = string
  validation {
    condition     = can(regex("^https://", var.zero_portal_url))
    error_message = "zero_portal_url must be an HTTPS XConnect Zero portal URL."
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = { ManagedBy = "xconnect-lab", LabRun = var.run_id, ExpiresAt = var.expires_at, Environment = "uat" }
  }
}

# The UAT environment owns its network. This lab only attaches two disposable
# Spot nodes and their scoped security groups to the account's existing default
# VPC/subnet; it never creates a parallel VPC, subnet, route or internet gateway.
data "aws_vpc" "uat" { default = true }

locals {
  gateway_transport_access_enabled = length(var.gateway_transport_ingress_cidrs) > 0
}

resource "aws_security_group" "client" {
  name   = "${var.run_id}-client"
  vpc_id = data.aws_vpc.uat.id
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.runner_cidr]
  }
  dynamic "ingress" {
    for_each = var.ssh_debug_ingress_cidrs
    content {
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
      description = "Temporary operator SSH debugging from an explicitly allowed /32"
    }
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "gateway" {
  name   = "${var.run_id}-gateway"
  vpc_id = data.aws_vpc.uat.id
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.runner_cidr]
  }
  dynamic "ingress" {
    for_each = var.ssh_debug_ingress_cidrs
    content {
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
      description = "Temporary operator SSH debugging from an explicitly allowed /32"
    }
  }
  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.client.id]
    description     = "Xray TLS from the controlled client only"
  }
  dynamic "ingress" {
    for_each = var.gateway_transport_ingress_cidrs
    content {
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
      description = "Xray TLS from an explicitly allowed desktop /32"
    }
  }
  ingress {
    from_port       = 8443
    to_port         = 8443
    protocol        = "tcp"
    security_groups = [aws_security_group.client.id]
    description     = "Experimental lab-controller API from the controlled client"
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "gateway" {
  ami                         = var.aws_ami
  instance_type               = var.aws_gateway_instance_type
  vpc_security_group_ids      = [aws_security_group.gateway.id]
  associate_public_ip_address = true
  user_data = templatefile("${path.module}/bootstrap.sh", {
    role           = "relay"
    run_id         = var.run_id
    ssh_public_key = var.ssh_public_key
    expires_at     = var.expires_at
  })
  instance_market_options {
    market_type = "spot"
    spot_options {
      spot_instance_type             = "one-time"
      instance_interruption_behavior = "terminate"
    }
  }
  metadata_options { http_tokens = "required" }
  root_block_device {
    volume_size           = 12
    encrypted             = true
    delete_on_termination = true
  }
  timeouts { create = "5m" }
  tags = { Name = "${var.run_id}-gateway", XConnectRole = "relay" }
}

resource "aws_instance" "client" {
  ami                         = var.aws_ami
  instance_type               = var.aws_client_instance_type
  vpc_security_group_ids      = [aws_security_group.client.id]
  associate_public_ip_address = true
  user_data = templatefile("${path.module}/bootstrap.sh", {
    role           = "controlled-client"
    run_id         = var.run_id
    ssh_public_key = var.ssh_public_key
    expires_at     = var.expires_at
  })
  instance_market_options {
    market_type = "spot"
    spot_options {
      spot_instance_type             = "one-time"
      instance_interruption_behavior = "terminate"
    }
  }
  metadata_options { http_tokens = "required" }
  root_block_device {
    volume_size           = 12
    encrypted             = true
    delete_on_termination = true
  }
  timeouts { create = "5m" }
  tags = { Name = "${var.run_id}-client", XConnectRole = "controlled-client" }
}

output "gateway_provider" { value = var.gateway_provider }
output "gateway_role" { value = "relay" }
output "client_role" { value = "controlled-client" }
output "client_ip" { value = aws_instance.client.public_ip }
output "client_private_ip" { value = aws_instance.client.private_ip }

output "gateway_ip" { value = aws_instance.gateway.public_ip }
output "gateway_private_ip" { value = aws_instance.gateway.private_ip }
output "gateway_transport_ip" {
  value = local.gateway_transport_access_enabled ? aws_instance.gateway.public_ip : aws_instance.gateway.private_ip
}
output "gateway_transport_access_enabled" { value = local.gateway_transport_access_enabled }
output "ssh_debug_access_enabled" { value = length(var.ssh_debug_ingress_cidrs) > 0 }
output "gateway_ssh_user" { value = "ubuntu" }

output "client_ssh_user" { value = "ubuntu" }
output "zero_accounts_api_url" { value = var.zero_accounts_api_url }
output "zero_portal_url" { value = var.zero_portal_url }

output "lab_controller_url" {
  value = "https://${aws_instance.gateway.public_ip}:8443"
}

output "resource_ids" {
  value = {
    client         = aws_instance.client.id
    gateway        = aws_instance.gateway.id
    gateway_role   = "relay"
    client_role    = "controlled-client"
    gateway_source = var.gateway_provider
    run            = var.run_id
  }
}
