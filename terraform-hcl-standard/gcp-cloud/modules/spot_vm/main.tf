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

variable "network_tags" {
  type    = list(string)
  default = []
}

variable "public_ip" {
  type    = bool
  default = false
}

variable "ssh_public_key" {
  type    = string
  default = ""
}

variable "ssh_username" {
  type    = string
  default = "github-actions"
}

variable "enable_oslogin" {
  description = "Whether this VM uses GCP OS Login instead of instance metadata SSH keys."
  type        = bool
  default     = false
}

variable "max_run_duration_seconds" {
  description = "Optional maximum lifetime. Omit for a service host that must not expire after one hour."
  type        = number
  default     = null

  validation {
    condition     = var.max_run_duration_seconds == null ? true : var.max_run_duration_seconds >= 60
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
  tags                      = var.network_tags
  # Never write enable-oslogin=FALSE: projects under the requireOsLogin
  # organization policy reject it (HTTP 412). OS Login VMs take SSH keys from
  # the deploy principal's OS Login profile, so they carry no metadata keys.
  metadata = merge(
    var.enable_oslogin ? { "enable-oslogin" = "TRUE" } : {},
    var.enable_oslogin || trimspace(var.ssh_public_key) == "" ? {} : {
      "ssh-keys" = "${var.ssh_username}:${trimspace(var.ssh_public_key)}"
    }
  )

  lifecycle {
    precondition {
      condition     = !var.public_ip || var.enable_oslogin || trimspace(var.ssh_public_key) != ""
      error_message = "A public Spot VM requires OS Login or an SSH public key from the deploy environment."
    }
  }

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
    dynamic "access_config" {
      for_each = var.public_ip ? [1] : []
      content {}
    }
  }

  scheduling {
    automatic_restart           = false
    on_host_maintenance         = "TERMINATE"
    preemptible                 = true
    provisioning_model          = "SPOT"
    instance_termination_action = "STOP"

    dynamic "max_run_duration" {
      for_each = var.max_run_duration_seconds == null ? [] : [var.max_run_duration_seconds]
      content {
        seconds = max_run_duration.value
      }
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

output "public_ip" {
  value = try(google_compute_instance.this.network_interface[0].access_config[0].nat_ip, null)
}

output "private_ip" {
  value = google_compute_instance.this.network_interface[0].network_ip
}
