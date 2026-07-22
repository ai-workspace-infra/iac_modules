variable "label" {
  description = "Replacement instance label."
  type        = string
}

variable "region" {
  description = "Vultr region code."
  type        = string
}

variable "target_plan" {
  description = "Vultr plan for the replacement instance."
  type        = string
}

variable "os_id" {
  description = "Vultr OS ID when creating from a clean image."
  type        = number
  default     = null
}

variable "snapshot_id" {
  description = "Optional Vultr snapshot used to restore the replacement instance."
  type        = string
  default     = null
}

variable "enable_ipv6" {
  description = "Whether IPv6 should be enabled."
  type        = bool
  default     = true
}

variable "backups" {
  description = "Whether automatic backups should be enabled on the replacement."
  type        = bool
  default     = true
}

variable "backup_schedule_type" {
  description = "Vultr backup schedule type when automatic backups are enabled."
  type        = string
  default     = "daily"

  validation {
    condition     = contains(["daily", "weekly", "monthly", "daily_alt_even", "daily_alt_odd"], var.backup_schedule_type)
    error_message = "backup_schedule_type must be a Vultr-supported schedule type."
  }
}

variable "tags" {
  description = "Tags applied to the replacement instance."
  type        = list(string)
  default     = []
}

variable "ssh_key_ids" {
  description = "SSH key IDs attached to the replacement instance."
  type        = list(string)
  default     = []
}

variable "user_data" {
  description = "Cloud-init user data for the replacement instance."
  type        = string
  default     = ""
}

variable "vpc_id" {
  description = "Optional VPC ID."
  type        = string
  default     = null
}

variable "operation_id" {
  description = "Resize operation ID used for traceability."
  type        = string
}

check "source_image" {
  assert {
    condition     = var.snapshot_id != null || var.os_id != null
    error_message = "Either snapshot_id or os_id must be provided."
  }
}
