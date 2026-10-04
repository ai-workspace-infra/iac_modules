terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

variable "project_id" { type = string }
variable "name" { type = string }
variable "zone" { type = string }
variable "size_gb" {
  type = number
  validation {
    condition     = var.size_gb >= 50
    error_message = "A release backup data disk must be at least 50 GiB."
  }
}
variable "disk_type" {
  type    = string
  default = "pd-balanced"
  validation {
    condition     = contains(["pd-balanced", "pd-ssd", "pd-standard"], var.disk_type)
    error_message = "disk_type must be a supported persistent disk type."
  }
}
variable "labels" {
  type    = map(string)
  default = {}
}

# The disk has its own Terraform resource identity and outlives VM replacement.
# An intentional deletion requires a separately reviewed protection removal.
resource "google_compute_disk" "this" {
  project         = var.project_id
  name            = var.name
  zone            = var.zone
  size            = var.size_gb
  type            = var.disk_type
  labels          = var.labels
  deletion_policy = "PREVENT"

  lifecycle {
    prevent_destroy = true
  }
}

output "id" { value = google_compute_disk.this.id }
output "name" { value = google_compute_disk.this.name }
