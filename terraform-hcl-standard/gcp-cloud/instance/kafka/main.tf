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

module "pubsub" {
  source       = "../../modules/msk"
  project_id   = var.project_id
  topic        = "dev-topic"
  subscription = "dev-subscription"
}

output "topic" {
  value = module.pubsub.topic
}
