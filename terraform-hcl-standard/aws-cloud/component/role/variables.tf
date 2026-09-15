variable "config_files" {
  description = "Absolute GitOps path in a one-item list: [account_config]."
  type        = list(string)
  nullable    = false
  validation {
    condition     = length(var.config_files) == 1
    error_message = "Pass exactly one GitOps declaration path for account_config."
  }
}
