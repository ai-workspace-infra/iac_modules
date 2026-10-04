terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

variable "project_id" { type = string }
variable "region" { type = string }
variable "service_name" { type = string }
variable "image" { type = string }
variable "service_account" { type = string }
resource "google_cloud_run_v2_service" "this" {
  project  = var.project_id
  name     = var.service_name
  location = var.region

  template {
    service_account = var.service_account

    containers {
      image = var.image
    }
  }
}

output "uri" {
  value = google_cloud_run_v2_service.this.uri
}
