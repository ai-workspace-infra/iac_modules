variable "name" {
  description = "EIP name."
  type        = string
}

variable "bandwidth" {
  description = "EIP bandwidth in Mbps."
  type        = number
}

variable "internet_type" {
  description = "EIP route type: bgp or international."
  type        = string
  default     = "bgp"
}

variable "charge_mode" {
  description = "EIP billing mode, such as bandwidth or traffic."
  type        = string
  default     = "bandwidth"
}

variable "tag" {
  description = "UCloud resource tag."
  type        = string
  default     = "Default"
}

resource "ucloud_eip" "this" {
  name          = var.name
  bandwidth     = var.bandwidth
  internet_type = var.internet_type
  charge_mode   = var.charge_mode
  tag           = var.tag
}

output "eip_id" {
  description = "UCloud EIP ID."
  value       = ucloud_eip.this.id
}

output "public_ip" {
  description = "Allocated public IP address."
  value       = ucloud_eip.this.public_ip
}
