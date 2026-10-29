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
  description = "Desired filesystem metadata; Playbooks owns formatting"
  type        = string
  default     = "ext4"
}

variable "linode_id" {
  description = "Instance ID to attach"
  type        = number
}

resource "linode_volume" "this" {
  label     = var.label
  region    = var.region
  size      = var.size
  linode_id = var.linode_id
}

output "volume_id" {
  description = "Block Storage volume ID"
  value       = linode_volume.this.id
}

output "filesystem_path" {
  value = linode_volume.this.filesystem_path
}

output "size_gb" {
  value = linode_volume.this.size
}

output "region" {
  value = linode_volume.this.region
}

output "label" {
  value = linode_volume.this.label
}

output "linode_id" {
  value = linode_volume.this.linode_id
}
