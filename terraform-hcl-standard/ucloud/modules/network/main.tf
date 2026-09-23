variable "name" {
  description = "Name assigned to the VPC and subnet."
  type        = string
}

variable "tag" {
  description = "UCloud resource tag."
  type        = string
  default     = "Default"
}

variable "cidr_blocks" {
  description = "IPv4 CIDR blocks for the VPC."
  type        = list(string)
}

variable "subnet_cidr_block" {
  description = "IPv4 CIDR block for the subnet."
  type        = string
}

resource "ucloud_vpc" "this" {
  name        = var.name
  tag         = var.tag
  cidr_blocks = var.cidr_blocks
}

resource "ucloud_subnet" "this" {
  name       = var.name
  tag        = var.tag
  cidr_block = var.subnet_cidr_block
  vpc_id     = ucloud_vpc.this.id
}

output "vpc_id" {
  description = "UCloud VPC ID."
  value       = ucloud_vpc.this.id
}

output "subnet_id" {
  description = "UCloud subnet ID."
  value       = ucloud_subnet.this.id
}
