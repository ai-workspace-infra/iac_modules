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
}

resource "google_project" "this" {
  project_id      = var.project_id
  name            = var.name
  org_id          = var.organization_id
  billing_account = var.billing_account_id
  deletion_policy = "PREVENT"
}

resource "google_project_service" "compute" {
  project            = google_project.this.project_id
  service            = "compute.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "run" {
  project            = google_project.this.project_id
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifact_registry" {
  project            = google_project.this.project_id
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iam_credentials" {
  project            = google_project.this.project_id
  service            = "iamcredentials.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "sts" {
  project            = google_project.this.project_id
  service            = "sts.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "logging" {
  project            = google_project.this.project_id
  service            = "logging.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "monitoring" {
  project            = google_project.this.project_id
  service            = "monitoring.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "secret_manager" {
  project            = google_project.this.project_id
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

output "project_id" {
  value = google_project.this.project_id
}

output "project_number" {
  value = google_project.this.number
}
