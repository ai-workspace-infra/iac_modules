variable "project_id" {
  description = "Project id"
  type        = string
}

variable "name" {
  description = "Instance name"
  type        = string
}

variable "zone" {
  description = "Instance zone"
  type        = string
  default     = "us-central1-a"
}

variable "machine_type" {
  description = "Machine type"
  type        = string
  default     = "e2-medium"
}

variable "network" {
  description = "Network self link"
  type        = string
}

variable "subnet" {
  description = "Subnetwork self link"
  type        = string
}

variable "image" {
  description = "Source image"
  type        = string
}

variable "ssh_keys" {
  description = "SSH key metadata entries"
  type        = list(string)
  default     = []
}

variable "network_tags" {
  description = "Firewall target tags for the VPS role"
  type        = list(string)
  default     = []
}

variable "startup_script" {
  description = "Optional non-secret startup script"
  type        = string
  default     = ""
}

resource "google_compute_instance" "vm" {
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
}

output "instance_self_link" {
  value       = google_compute_instance.vm.self_link
  description = "Instance self link"
}

output "private_ip" {
  value       = google_compute_instance.vm.network_interface[0].network_ip
  description = "VPC private IPv4 address"
}

output "public_ip" {
  value       = google_compute_instance.vm.network_interface[0].access_config[0].nat_ip
  description = "Ephemeral public IPv4 address"
}
