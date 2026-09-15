variable "bootstrap_project_id" {
  type        = string
  description = "Existing project used to run the bootstrap credentials."
}

variable "project_id" {
  type        = string
  description = "Project ID declared in the resource YAML."
}

variable "project_name" {
  type        = string
  description = "Human readable project name."
}

variable "organization_id" {
  type        = string
  description = "xworktech.com organization resource ID."
}

variable "billing_account_id" {
  type        = string
  sensitive   = true
  description = "Billing account supplied through TF_VAR_billing_account_id."
}

variable "region" {
  type    = string
  default = "asia-east1"
}

variable "github_owner" {
  type = string
}

variable "github_repository" {
  type = string
}

variable "network_name" {
  type = string
}

variable "subnet_cidr" {
  type = string
}

variable "artifact_registry_location" {
  type = string
}

variable "artifact_registry_id" {
  type = string
}

variable "cloud_run_service_name" {
  type = string
}

variable "cloud_run_image" {
  type = string
}
