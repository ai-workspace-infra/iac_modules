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

module "bucket" {
  source     = "../../modules/s3"
  project_id = var.project_id
  name       = "dev-object-${var.project_id}"
  location   = "US"
}

output "bucket" {
  value = module.bucket.bucket
}
