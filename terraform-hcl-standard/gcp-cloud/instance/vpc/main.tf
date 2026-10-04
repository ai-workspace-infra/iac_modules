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
variable "region" {
  type    = string
  default = "us-central1"
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "vpc" {
  source     = "../../modules/vpc"
  project_id = var.project_id
  subnets = [
    {
      name          = "dev-subnet"
      ip_cidr_range = "10.20.0.0/24"
      region        = var.region
    }
  ]
}

output "network" {
  value = module.vpc.network_self_link
}
