terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

variable "project_id" {
  type        = string
  description = "Target project"
}

variable "region" {
  type    = string
  default = "us-central1"
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "landingzone" {
  source     = "../../modules/landingzone"
  project_id = var.project_id
}

output "enabled_services" {
  value       = module.landingzone.enabled_services
  description = "APIs enabled for the project"
}
