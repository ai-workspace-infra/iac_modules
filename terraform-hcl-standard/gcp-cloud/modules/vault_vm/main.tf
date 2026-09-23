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

variable "network" {
  type = string
}

variable "subnetwork" {
  type = string
}

variable "image" {
  type    = string
  default = "projects/debian-cloud/global/images/family/debian-12"
}

variable "xconnect_role" {
  type        = string
  description = "Shared Vault XConnect role: gateway or one."
  validation {
    condition     = contains(["gateway", "one"], var.xconnect_role)
    error_message = "xconnect_role must be gateway or one."
  }
}

variable "public_ip" {
  type        = bool
  description = "Whether this node receives a static external IPv4 address."
  default     = false
}

resource "google_compute_address" "public" {
  count        = var.public_ip ? 1 : 0
  project      = var.project_id
  name         = "${var.name}-public-ip"
  region       = replace(var.zone, "/-[a-z]$/", "")
  address_type = "EXTERNAL"
  network_tier = "PREMIUM"
}

resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "${var.name}-runtime"
  display_name = "${var.name} runtime"
}

resource "google_compute_instance" "this" {
  project                   = var.project_id
  name                      = var.name
  zone                      = var.zone
  machine_type              = var.machine_type
  allow_stopping_for_update = true
  tags                      = var.xconnect_role == "gateway" ? ["vault", "vault-gateway"] : ["vault", "vault-one"]

  boot_disk {
    initialize_params {
      image = var.image
      size  = 50
      type  = "pd-balanced"
    }
  }

  network_interface {
    network    = var.network
    subnetwork = var.subnetwork

    dynamic "access_config" {
      for_each = var.public_ip ? [1] : []
      content {
        nat_ip       = google_compute_address.public[0].address
        network_tier = "PREMIUM"
      }
    }
  }

  service_account {
    email  = google_service_account.runtime.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
}

output "self_link" {
  value = google_compute_instance.this.self_link
}

output "private_ip" {
  value = google_compute_instance.this.network_interface[0].network_ip
}

output "public_ip" {
  value = var.public_ip ? google_compute_address.public[0].address : null
}
