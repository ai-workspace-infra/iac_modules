

variable "account_config_path" {
  description = "Absolute path to the account declaration in the GitOps repository."
  type        = string
  nullable    = false
}

variable "ec2_config_path" {
  description = "Absolute path to the ec2 declaration in the GitOps repository."
  type        = string
  nullable    = false
}
