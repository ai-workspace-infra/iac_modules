

variable "account_config_path" {
  description = "Absolute path to the account declaration in the GitOps repository."
  type        = string
  nullable    = false
}

variable "rds_config_path" {
  description = "Absolute path to the rds declaration in the GitOps repository."
  type        = string
  nullable    = false
}
