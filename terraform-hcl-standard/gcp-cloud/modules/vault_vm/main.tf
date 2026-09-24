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

variable "enable_oslogin" {
  type        = bool
  description = "Enable IAM-based OS Login for IAP SSH access."
  default     = false
}

variable "os_login_principal_email" {
  type        = string
  description = "The WIF deployment service account that receives OS Login access."
  default     = ""
  validation {
    condition     = !var.enable_oslogin || can(regex("^[^@]+@[^@]+\\.iam\\.gserviceaccount\\.com$", var.os_login_principal_email))
    error_message = "os_login_principal_email must be a service-account email when OS Login is enabled."
  }
}

variable "ssh_public_key" {
  type        = string
  description = "Optional metadata-based SSH public key; ignored when OS Login is enabled."
  default     = ""
}

variable "ssh_username" {
  type        = string
  description = "Linux username for the metadata-based SSH public key."
  default     = "github-actions"
  validation {
    condition     = can(regex("^[a-z_][a-z0-9_-]{0,31}$", var.ssh_username))
    error_message = "ssh_username must be a valid Linux username."
  }
}

locals {
  instance_metadata = merge(
    var.enable_oslogin ? { "enable-oslogin" = "TRUE" } : {},
    !var.enable_oslogin && trimspace(var.ssh_public_key) != "" ? {
      "ssh-keys" = "${var.ssh_username}:${trimspace(var.ssh_public_key)}"
    } : {},
  )
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

resource "google_service_account_iam_member" "os_login_act_as" {
  count              = var.enable_oslogin ? 1 : 0
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.os_login_principal_email}"
}

resource "google_compute_instance" "this" {
  project                   = var.project_id
  name                      = var.name
  zone                      = var.zone
  machine_type              = var.machine_type
  allow_stopping_for_update = true
  tags                      = var.xconnect_role == "gateway" ? ["vault", "vault-gateway"] : ["vault", "vault-one"]
  metadata                  = local.instance_metadata

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
