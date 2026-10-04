terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

variable "project_id" { type = string }
variable "location" { type = string }
variable "repository_id" { type = string }

resource "google_artifact_registry_repository" "this" {
  project       = var.project_id
  location      = var.location
  repository_id = var.repository_id
  format        = "DOCKER"
  description   = "Immutable container images for XWork services"
}

output "repository" {
  value = google_artifact_registry_repository.this.name
}
