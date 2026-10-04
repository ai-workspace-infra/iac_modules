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

module "landingzone" {
  source     = "../../modules/landingzone"
  project_id = var.project_id
  services = [
    "compute.googleapis.com",
    "pubsub.googleapis.com",
    "sqladmin.googleapis.com",
    "redis.googleapis.com"
  ]
}

output "services" {
  value = module.landingzone.enabled_services
}
