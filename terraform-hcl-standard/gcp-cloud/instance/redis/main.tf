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

module "redis" {
  source         = "../../modules/redis"
  project_id     = var.project_id
  name           = "dev-redis"
  region         = var.region
  memory_size_gb = 2
}

output "redis_host" {
  value = module.redis.host
}
