variable "oidc_url" {
  description = "HTTPS issuer URL for the external OIDC provider."
  type        = string

  validation {
    condition     = can(regex("^https://[^/]+(/.*)?$", var.oidc_url))
    error_message = "oidc_url must be an HTTPS issuer URL."
  }
}

variable "client_id" {
  description = "Allowed OIDC audience/client ID."
  type        = string
  validation {
    condition     = trimspace(var.client_id) != ""
    error_message = "client_id must not be empty."
  }
}

variable "thumbprint_list" {
  description = "CA thumbprints accepted by IAM for the provider TLS chain."
  type        = list(string)
  sensitive   = false
  validation {
    condition     = length(var.thumbprint_list) > 0 && alltrue([for value in var.thumbprint_list : can(regex("^[0-9a-fA-F]{40}$", value))])
    error_message = "thumbprint_list must contain at least one 40-character SHA-1 thumbprint."
  }
}

variable "role_name" {
  description = "IAM role trusted by the OIDC provider."
  type        = string
  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,64}$", var.role_name))
    error_message = "role_name must be a valid IAM role name."
  }
}

variable "subject" {
  description = "Exact OIDC subject claim allowed to assume the role."
  type        = string
  validation {
    condition     = trimspace(var.subject) != "" && !strcontains(var.subject, "*")
    error_message = "subject must be explicit and must not contain wildcards."
  }
}
