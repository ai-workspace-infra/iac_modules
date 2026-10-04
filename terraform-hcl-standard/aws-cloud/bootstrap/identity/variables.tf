variable "bootstrap_config_path" {
  description = "Path to the bootstrap account configuration YAML"
  type        = string

  validation {
    condition     = var.bootstrap_config_path != null && trimspace(var.bootstrap_config_path) != ""
    error_message = "Set bootstrap_config_path (TF_CONFIG) to the bootstrap YAML file path."
  }
}

variable "github_actions_oidc_config_path" {
  description = "Optional path to the GitOps GitHub Actions AWS OIDC declaration. When omitted, bootstrap YAML must set github_actions_oidc.config_path."
  type        = string
  default     = null

  validation {
    condition     = var.github_actions_oidc_config_path == null || trimspace(var.github_actions_oidc_config_path) != ""
    error_message = "github_actions_oidc_config_path must be null or a non-empty path."
  }
}
