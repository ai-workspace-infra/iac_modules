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
variable "zone" {
  type    = string
  default = "us-central1-a"
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

module "vpc" {
  source     = "../../modules/vpc"
  project_id = var.project_id
  subnets = [{
    name          = "nlb-subnet"
    ip_cidr_range = "10.30.0.0/24"
    region        = var.region
  }]
}

module "nlb" {
  source     = "../../modules/nlb"
  project_id = var.project_id
  network    = module.vpc.network_self_link
  subnet     = module.vpc.subnet_self_links[0]
  port       = 8080
  zone       = var.zone
  name       = "dev-nlb"
}

output "forwarding_rule" {
  value = module.nlb.forwarding_rule
}
