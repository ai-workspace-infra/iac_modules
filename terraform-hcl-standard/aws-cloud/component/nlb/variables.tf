

variable "account_config_path" {
  description = "Absolute path to the account declaration in the GitOps repository."
  type        = string
  nullable    = false
}

variable "nlb_config_path" {
  description = "Absolute path to the nlb declaration in the GitOps repository."
  type        = string
  nullable    = false
}
