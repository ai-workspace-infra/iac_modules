variable "project_id" {
  description = "GCP project id"
  type        = string
}

variable "name" {
  description = "Compute Engine instance name"
  type        = string
}

variable "zone" {
  description = "Compute Engine zone"
  type        = string
}

variable "machine_type" {
  description = "Compute Engine machine type"
  type        = string
}

variable "network" {
  description = "VPC self link"
  type        = string
}

variable "subnet" {
  description = "Subnetwork self link"
  type        = string
}

variable "image" {
  description = "Immutable image self link or family reference"
  type        = string
}

variable "ssh_keys" {
  description = "SSH metadata entries"
  type        = list(string)
  default     = []
}

variable "network_tags" {
  description = "Firewall target tags"
  type        = list(string)
  default     = []
}

variable "startup_script" {
  description = "Non-secret startup script, including the UAT TTL guard"
  type        = string
  default     = ""
}

resource "google_compute_instance" "this" {
  name         = var.name
  project      = var.project_id
  zone         = var.zone
  machine_type = var.machine_type
  tags         = var.network_tags

  boot_disk {
    initialize_params {
      image = var.image
    }
  }

  network_interface {
    network    = var.network
    subnetwork = var.subnet
    access_config {}
  }

  metadata = length(var.ssh_keys) > 0 ? {
    ssh-keys = join("\n", var.ssh_keys)
  } : {}

  metadata_startup_script = var.startup_script != "" ? var.startup_script : null

  scheduling {
    provisioning_model          = "SPOT"
    instance_termination_action = "DELETE"
    automatic_restart           = false
    on_host_maintenance         = "TERMINATE"
  }
}
