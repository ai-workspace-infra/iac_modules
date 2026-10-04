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

module "sql" {
  source           = "../../modules/rds"
  project_id       = var.project_id
  name             = "dev-postgres"
  database_version = "POSTGRES_15"
  region           = var.region
  tier             = "db-custom-1-3840"
}

output "connection_name" {
  value = module.sql.connection_name
}
