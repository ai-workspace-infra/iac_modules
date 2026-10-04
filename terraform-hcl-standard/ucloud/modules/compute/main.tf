variable "name" {
  description = "UHost instance name."
  type        = string
}

variable "availability_zone" {
  description = "Availability zone, for example cn-bj2-03."
  type        = string
}

variable "image_id" {
  description = "UCloud image ID."
  type        = string
}

variable "instance_type" {
  description = "UHost instance type, for example n-basic-2."
  type        = string
}

variable "boot_disk_type" {
  description = "Boot disk type supported by the selected zone, for example cloud_ssd."
  type        = string
  default     = "cloud_ssd"
}

variable "security_group_id" {
  description = "UCloud firewall security group ID."
  type        = string
}

variable "vpc_id" {
  description = "Optional VPC ID. When set, subnet_id must also be set."
  type        = string
  default     = null
}

variable "subnet_id" {
  description = "Optional subnet ID used with vpc_id."
  type        = string
  default     = null
}

variable "tag" {
  description = "UCloud resource tag."
  type        = string
  default     = "Default"
}

variable "login_mode" {
  description = "Instance login mode: Password or KeyPair."
  type        = string
  default     = "KeyPair"
}

variable "key_pair_id" {
  description = "UCloud key pair ID, required when login_mode is KeyPair."
  type        = string
  default     = null
}

variable "root_password" {
  description = "Root password, required for Password login mode. Supply through a secret variable."
  type        = string
  sensitive   = true
  default     = null
}

variable "user_data" {
  description = "Cloud-init/user data passed to the instance."
  type        = string
  default     = null
}

variable "deletion_protection" {
  description = "Protect the instance from deletion. Disable this before destroying a protected instance."
  type        = bool
  default     = false
}

resource "ucloud_instance" "this" {
  availability_zone   = var.availability_zone
  image_id            = var.image_id
  instance_type       = var.instance_type
  name                = var.name
  tag                 = var.tag
  boot_disk_type      = var.boot_disk_type
  security_group      = var.security_group_id
  vpc_id              = var.vpc_id
  subnet_id           = var.subnet_id
  login_mode          = var.login_mode
  key_pair_id         = var.key_pair_id
  root_password       = var.root_password
  user_data           = var.user_data
  deletion_protection = var.deletion_protection
}

output "instance_id" {
  description = "UHost instance ID."
  value       = ucloud_instance.this.id
}

output "ip_set" {
  description = "Instance IP addresses reported by UCloud."
  value       = ucloud_instance.this.ip_set
}

output "status" {
  description = "Current UHost instance status."
  value       = ucloud_instance.this.status
}
