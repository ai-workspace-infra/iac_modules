

variable "account_config_path" {
  description = "Absolute path to the account declaration in the GitOps repository."
  type        = string
  nullable    = false
}

variable "kafka_config_path" {
  description = "Absolute path to the kafka declaration in the GitOps repository."
  type        = string
  nullable    = false
}
