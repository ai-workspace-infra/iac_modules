terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

variable "project_id" { type = string }

provider "google" {
  project = var.project_id
  region  = "us-central1"
}

module "iam" {
  source     = "../../modules/iam"
  project_id = var.project_id
  bindings = [
    { role = "roles/storage.objectViewer", member = "allAuthenticatedUsers" }
  ]
}

output "roles" {
  value = module.iam.applied_bindings
}
