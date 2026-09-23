variable "bootstrap_project_id" {
  type        = string
  default     = ""
  description = "Existing project used to run the bootstrap credentials."
}

variable "project_id" {
  type        = string
  description = "Project ID declared in the resource YAML."
}

variable "project_name" {
  type        = string
  default     = ""
  description = "Human readable project name."
}

variable "organization_id" {
  type        = string
  default     = ""
  description = "xworktech.com organization resource ID."
}

variable "billing_account_id" {
  type        = string
  default     = null
  sensitive   = true
  description = "Billing account supplied through TF_VAR_billing_account_id."
}

variable "create_project" {
  type        = bool
  default     = false
  description = "Create the target project. The post-bootstrap platform path normally manages an existing project."
}

variable "region" {
  type    = string
  default = "asia-east1"
}

variable "github_owner" {
  type    = string
  default = "ai-workspace-infra"
}

variable "github_repository" {
  type    = string
  default = "platform-ops-toolkit"
}

variable "deploy_service_account" {
  type        = string
  description = "Existing environment deploy Service Account created by bootstrap/identity."
}

variable "workload_identity_provider" {
  type        = string
  description = "Existing environment Workload Identity Provider created by bootstrap/identity."
}

variable "network_name" {
  type    = string
  default = null
}

variable "subnet_cidr" {
  type    = string
  default = null
}

variable "enable_cloud_nat" {
  type        = bool
  default     = true
  description = "Create Cloud NAT for private subnet egress. Disable for short-lived validation workloads that need no outbound internet."
}

variable "artifact_registry_location" {
  type    = string
  default = null
}

variable "artifact_registry_id" {
  type    = string
  default = null
}

variable "cloud_run_service_name" {
  type    = string
  default = null
}

variable "cloud_run_image" {
  type    = string
  default = null
}
