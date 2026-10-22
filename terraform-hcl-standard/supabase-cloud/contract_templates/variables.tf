variable "project_ref" {
  description = "Existing Supabase project reference. Set this for import and connection discovery."
  type        = string
  default     = null
  nullable    = true
}

variable "organization_id" {
  description = "Supabase organization slug used when creating a project."
  type        = string
}

variable "project_name" {
  description = "Supabase project name."
  type        = string
}

variable "region" {
  description = "Supabase database region."
  type        = string
}

variable "instance_size" {
  description = "Optional Supabase compute instance size."
  type        = string
  default     = null
  nullable    = true
}

variable "database_password" {
  description = "Supabase database password, injected from Vault or TF_VAR_database_password."
  type        = string
  sensitive   = true
}

variable "database_username" {
  description = "Database user name used by the application connection contract."
  type        = string
}

variable "database_name" {
  description = "Database name used by the application connection contract."
  type        = string
  default     = "postgres"
}

variable "pooler_mode" {
  description = "Supavisor URI to expose when database_uri is not supplied: session or transaction."
  type        = string
  default     = "session"

  validation {
    condition     = contains(["session", "transaction"], var.pooler_mode)
    error_message = "pooler_mode must be session or transaction."
  }
}

variable "management_mode" {
  type        = string
  description = "Explicit managed lifecycle; external projects use resource-free rendered root."
  default     = "existing_external"
  validation {
    condition     = contains(["create_new", "adopt_existing", "existing_external"], var.management_mode)
    error_message = "Explicit supported lifecycle required."
  }
}
variable "strict_no_secret_state" {
  type    = bool
  default = true
}
variable "ack_sensitive_state" {
  type    = bool
  default = false
}
variable "explicit_adoption" {
  type    = bool
  default = false
}
