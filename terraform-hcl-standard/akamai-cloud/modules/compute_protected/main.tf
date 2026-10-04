variable "label" {
  description = "Linode instance label"
  type        = string
}

variable "region" {
  description = "Linode region"
  type        = string
}

variable "type" {
  description = "Linode plan"
  type        = string
}

variable "image" {
  description = "Linode image ID"
  type        = string
}

variable "private_ip" {
  description = "Enable private networking in the region"
  type        = bool
  default     = true
}

variable "firewall_id" {
  description = "Optional Linode Firewall ID"
  type        = number
  default     = null
}

variable "authorized_keys" {
  description = "SSH public keys installed for root"
  type        = list(string)
}

variable "user_data" {
  description = "Cloud-init exposed through the Linode Metadata service"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Linode tags"
  type        = list(string)
  default     = []
}

resource "linode_instance" "this" {
  label           = var.label
  region          = var.region
  type            = var.type
  image           = var.image
  private_ip      = var.private_ip
  firewall_id     = var.firewall_id
  authorized_keys = var.authorized_keys
  tags            = var.tags

  metadata {
    user_data = base64encode(var.user_data)
  }

  lifecycle {
    prevent_destroy = true
  }
}

output "instance_id" {
  description = "Linode instance ID"
  value       = linode_instance.this.id
}

output "main_ip" {
  description = "Public IPv4 address"
  value       = tolist(linode_instance.this.ipv4)[0]
}

output "private_ip" {
  description = "Private IPv4 address"
  value       = linode_instance.this.private_ip_address
}

output "ipv6" {
  description = "Primary IPv6 address list"
  value       = linode_instance.this.ipv6
}
