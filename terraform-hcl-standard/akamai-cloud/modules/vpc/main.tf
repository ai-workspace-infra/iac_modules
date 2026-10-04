variable "label" {
  description = "VPC label"
  type        = string
}

variable "region" {
  description = "Linode region"
  type        = string
}

variable "description" {
  description = "VPC description"
  type        = string
  default     = ""
}

variable "subnet_label" {
  description = "VPC subnet label"
  type        = string
  default     = "default"
}

variable "subnet_ipv4" {
  description = "VPC subnet IPv4 CIDR"
  type        = string
  default     = "10.0.0.0/24"
}

resource "linode_vpc" "this" {
  label       = var.label
  region      = var.region
  description = var.description
}

resource "linode_vpc_subnet" "this" {
  vpc_id = linode_vpc.this.id
  label  = var.subnet_label
  ipv4   = var.subnet_ipv4
}

output "vpc_id" {
  description = "VPC ID"
  value       = linode_vpc.this.id
}

output "subnet_id" {
  description = "VPC subnet ID"
  value       = linode_vpc_subnet.this.id
}
