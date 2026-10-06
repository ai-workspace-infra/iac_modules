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

variable "provisioning_model" {
  description = "SPOT for legacy disposable VMs; STANDARD for durable service hosts."
  type        = string
  default     = "SPOT"

  validation {
    condition     = contains(["SPOT", "STANDARD"], var.provisioning_model)
    error_message = "provisioning_model must be SPOT or STANDARD."
  }
}

variable "deletion_protection" {
  description = "Protect a durable service host against accidental API deletion."
  type        = bool
  default     = false
}

variable "data_disk_id" {
  description = "Optional independently managed persistent data disk."
  type        = string
  default     = ""
}

variable "data_disk_device_name" {
  description = "Stable Linux /dev/disk/by-id/google-* name for the data disk."
  type        = string
  default     = "web-saas-data"
}

resource "google_compute_instance" "this" {
  project                   = var.project_id
  name                      = var.name
  zone                      = var.zone
  machine_type              = var.machine_type
  allow_stopping_for_update = true
  labels                    = var.labels
  tags                      = var.network_tags
  deletion_protection       = var.deletion_protection
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
    # google_compute_attached_disk owns attachments declared outside this
    # module. Ignoring the instance's read-back prevents the two Terraform
    # resources from detaching or replacing one another's disks.
    ignore_changes = [attached_disk]

    precondition {
      condition     = !var.public_ip || var.enable_oslogin || trimspace(var.ssh_public_key) != ""
      error_message = "A public Spot VM requires OS Login or an SSH public key from the deploy environment."
    }
    precondition {
      condition     = var.provisioning_model != "STANDARD" || (var.deletion_protection && var.data_disk_id != "")
      error_message = "A STANDARD service host requires deletion protection and an independent data disk."
    }
    precondition {
      condition     = var.provisioning_model != "STANDARD" || var.max_run_duration_seconds == null
      error_message = "A STANDARD service host must not have a maximum run duration."
    }
  }

  boot_disk {
    auto_delete = var.provisioning_model == "SPOT"
    initialize_params {
      image = var.image
      size  = 20
      type  = "pd-balanced"
    }
  }

  dynamic "attached_disk" {
    for_each = var.data_disk_id == "" ? [] : [var.data_disk_id]
    content {
      source      = attached_disk.value
      device_name = var.data_disk_device_name
      mode        = "READ_WRITE"
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
    automatic_restart           = var.provisioning_model == "STANDARD"
    on_host_maintenance         = var.provisioning_model == "STANDARD" ? "MIGRATE" : "TERMINATE"
    preemptible                 = var.provisioning_model == "SPOT"
    provisioning_model          = var.provisioning_model
    instance_termination_action = var.provisioning_model == "SPOT" ? "STOP" : null

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
