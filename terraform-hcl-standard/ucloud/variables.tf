variable "ucloud_public_key" {
  description = "UCloud API public key; set with TF_VAR_ucloud_public_key or UCLOUD_PUBLIC_KEY."
  type        = string
  sensitive   = true
  default     = null
}

variable "ucloud_private_key" {
  description = "UCloud API private key; set with TF_VAR_ucloud_private_key or UCLOUD_PRIVATE_KEY."
  type        = string
  sensitive   = true
  default     = null
}

variable "ucloud_project_id" {
  description = "UCloud project ID; set with TF_VAR_ucloud_project_id or UCLOUD_PROJECT_ID."
  type        = string
  default     = null
}

variable "ucloud_region" {
  description = "UCloud region, for example cn-bj2; set with TF_VAR_ucloud_region or UCLOUD_REGION."
  type        = string
  default     = null
}

variable "ucloud_bootstrap_security_group_id" {
  description = "Security group ID emitted by the UCloud bootstrap Job."
  type        = string
  nullable    = false
}

variable "ucloud_bootstrap_key_pair_id" {
  description = "Key pair ID emitted by the UCloud bootstrap Job."
  type        = string
  nullable    = false
}
