variable "label" {
  description = "Block Storage volume label"
  type        = string
}

variable "region" {
  description = "Linode region"
  type        = string
}

variable "size" {
  description = "Volume size in GB"
  type        = number
}

variable "filesystem" {
  description = "Volume filesystem"
  type        = string
  default     = "ext4"
}

variable "linode_id" {
  description = "Instance ID to attach"
  type        = number
}

resource "linode_volume" "this" {
  label      = var.label
  region     = var.region
  size       = var.size
  filesystem = var.filesystem
  linode_id  = var.linode_id
}

output "volume_id" {
  description = "Block Storage volume ID"
  value       = linode_volume.this.id
}
