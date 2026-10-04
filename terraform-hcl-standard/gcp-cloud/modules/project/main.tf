terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

variable "project_id" {
  type        = string
  description = "Globally unique GCP project ID."
}

variable "name" {
  type        = string
  description = "Human readable project name."
}

variable "organization_id" {
  type        = string
  description = "Organization resource ID."
}

variable "billing_account_id" {
  type        = string
  description = "Billing account to attach to the project."
  sensitive   = true
  default     = null
}

variable "create_project" {
  type        = bool
  description = "Whether to create the project; false reads an existing project created outside this stack."
  default     = true
}

data "google_project" "existing" {
  count      = var.create_project ? 0 : 1
  project_id = var.project_id
}

resource "google_project" "this" {
  count           = var.create_project ? 1 : 0
  project_id      = var.project_id
  name            = var.name
  org_id          = var.organization_id
  billing_account = var.billing_account_id
  deletion_policy = "PREVENT"
}

locals {
  project_id     = var.create_project ? google_project.this[0].project_id : data.google_project.existing[0].project_id
  project_number = var.create_project ? google_project.this[0].number : data.google_project.existing[0].number
}

# Project APIs are enabled by bootstrap/identity (platform_services) so the
# runtime deploy identity only needs serviceusage.serviceUsageConsumer.

output "project_id" {
  value = local.project_id
}

output "project_number" {
  value = local.project_number
}
