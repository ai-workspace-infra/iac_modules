

variable "account_config_path" {
  description = "Absolute path to the account declaration in the GitOps repository."
  type        = string
  nullable    = false
}

variable "alb_config_path" {
  description = "Absolute path to the alb declaration in the GitOps repository."
  type        = string
  nullable    = false
}
