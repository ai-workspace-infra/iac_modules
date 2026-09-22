terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

variable "project_id" {
  type = string
}

variable "name" {
  type = string
}

variable "zone" {
  type = string
}

variable "machine_type" {
  type = string
}

variable "image" {
  type    = string
  default = "projects/debian-cloud/global/images/family/debian-12"
}

variable "network" {
  type = string
}

variable "subnetwork" {
  type = string
}

variable "labels" {
  type    = map(string)
  default = {}
}

variable "max_run_duration_seconds" {
  description = "Maximum lifetime of the disposable Spot instance before Compute Engine deletes it."
  type        = number
  default     = 3600

  validation {
    condition     = var.max_run_duration_seconds >= 60
    error_message = "max_run_duration_seconds must be at least 60 seconds."
  }
}

resource "google_compute_instance" "this" {
  project                   = var.project_id
  name                      = var.name
  zone                      = var.zone
  machine_type              = var.machine_type
  allow_stopping_for_update = true
  labels                    = var.labels

  boot_disk {
    initialize_params {
      image = var.image
      size  = 20
      type  = "pd-balanced"
    }
  }

  network_interface {
    network    = var.network
    subnetwork = var.subnetwork
  }

  scheduling {
    automatic_restart           = false
    on_host_maintenance         = "TERMINATE"
    preemptible                 = true
    provisioning_model          = "SPOT"
    instance_termination_action = "DELETE"

    max_run_duration {
      seconds = var.max_run_duration_seconds
    }
  }
}

output "name" {
  value = google_compute_instance.this.name
}

output "self_link" {
  value = google_compute_instance.this.self_link
}

output "zone" {
  value = google_compute_instance.this.zone
}

output "project_id" {
  value = google_compute_instance.this.project
}

output "provisioning_model" {
  value = google_compute_instance.this.scheduling[0].provisioning_model
}
