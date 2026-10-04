variable "config_files" {
  description = "Absolute GitOps paths in order: [account_config, vpc_config]."
  type        = list(string)
  nullable    = false
  validation {
    condition     = length(var.config_files) == 2
    error_message = "Pass exactly two GitOps declaration paths: account_config and vpc_config."
  }
}
