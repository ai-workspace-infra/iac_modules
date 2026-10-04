

variable "account_config_path" {
  description = "Absolute path to the account declaration in the GitOps repository."
  type        = string
  nullable    = false
}

variable "s3_config_path" {
  description = "Absolute path to the s3 declaration in the GitOps repository."
  type        = string
  nullable    = false
}
