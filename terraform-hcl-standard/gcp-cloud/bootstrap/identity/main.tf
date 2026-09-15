terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }

  # Terraform state uses the organization-wide S3-compatible object store.
  # Endpoint, bucket, key, credentials, and region are supplied by the
  # workflow from Vault's CICD state contract.
  backend "s3" {}
}

variable "access_token" {
  description = "Short-lived OAuth access token used by the bootstrap run."
  type        = string
  sensitive   = true
  default     = null
}

variable "project_id" {
  description = "Target project for IAM bootstrap"
  type        = string
}

variable "service_account_id" {
  description = "ID of the bootstrap service account"
  type        = string
  default     = "terraform-bootstrap"
}

variable "service_account_roles" {
  description = "List of roles to attach to the bootstrap service account"
  type        = list(string)
  default = [
    "roles/resourcemanager.projectIamAdmin",
    "roles/storage.admin",
    "roles/compute.admin",
    "roles/serviceusage.serviceUsageAdmin"
  ]
}

variable "environment" {
  description = "GitHub Actions environment bound to this identity."
  type        = string
}

variable "github_owner" {
  type = string
}

variable "github_repository" {
  type = string
}

variable "pool_id" {
  type    = string
  default = "github-actions"
}

variable "provider_id" {
  type    = string
  default = "github"
}

variable "audience" {
  description = "Explicit audience accepted from GitHub Actions."
  type        = string
}

variable "deploy_service_account_id" {
  type = string
}

variable "deploy_service_account_roles" {
  type = set(string)
  default = [
    "roles/artifactregistry.writer",
    "roles/run.admin",
    "roles/serviceusage.serviceUsageConsumer",
  ]
}

provider "google" {
  project      = var.project_id
  access_token = var.access_token
}

resource "google_project_service" "iam" {
  project = var.project_id
  service = "iam.googleapis.com"

  # Prevent accidental disablement of a core API when destroying the stack
  disable_on_destroy = false
}

resource "google_service_account" "bootstrap" {
  account_id   = var.service_account_id
  display_name = "Terraform Bootstrap"
  project      = var.project_id

  depends_on = [google_project_service.iam]
}

resource "google_project_iam_member" "bootstrap" {
  for_each = toset(var.service_account_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.bootstrap.email}"
}

resource "google_project_service" "iam_credentials" {
  project            = var.project_id
  service            = "iamcredentials.googleapis.com"
  disable_on_destroy = false
  depends_on         = [google_project_service.iam]
}

resource "google_project_service" "sts" {
  project            = var.project_id
  service            = "sts.googleapis.com"
  disable_on_destroy = false
  depends_on         = [google_project_service.iam]
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = var.pool_id
  display_name              = "GitHub Actions ${upper(var.environment)}"
  description               = "GitHub Actions OIDC federation for ${var.environment}"
  disabled                  = false
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = var.provider_id
  display_name                       = "GitHub Actions OIDC ${upper(var.environment)}"
  attribute_condition                = "assertion.repository == '${var.github_owner}/${var.github_repository}' && assertion.environment == '${var.environment}'"
  attribute_mapping = {
    "google.subject"        = "assertion.sub"
    "attribute.repository"  = "assertion.repository"
    "attribute.environment" = "assertion.environment"
    "attribute.ref"         = "assertion.ref"
  }

  oidc {
    issuer_uri        = "https://token.actions.githubusercontent.com"
    allowed_audiences = [var.audience]
  }
}

resource "google_service_account" "github_actions" {
  project      = var.project_id
  account_id   = var.deploy_service_account_id
  display_name = "GitHub Actions ${upper(var.environment)} deployer"
}

resource "google_project_iam_member" "deploy" {
  for_each = var.deploy_service_account_roles
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.github_actions.email}"
}

resource "google_service_account_iam_member" "federation" {
  service_account_id = google_service_account.github_actions.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_owner}/${var.github_repository}"
}

output "service_account_email" {
  value       = google_service_account.github_actions.email
  description = "GitHub Actions deploy service account email"
}

output "bootstrap_service_account_email" {
  value       = google_service_account.bootstrap.email
  description = "Bootstrap service account email"
}

output "workload_identity_provider" {
  value       = google_iam_workload_identity_pool_provider.github.name
  description = "Full resource name used by google-github-actions/auth."
}

output "project_id" {
  value = var.project_id
}
