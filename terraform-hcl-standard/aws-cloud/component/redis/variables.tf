

variable "account_config_path" {
  description = "Absolute path to the account declaration in the GitOps repository."
  type        = string
  nullable    = false
}

variable "redis_config_path" {
  description = "Absolute path to the redis declaration in the GitOps repository."
  type        = string
  nullable    = false
}
