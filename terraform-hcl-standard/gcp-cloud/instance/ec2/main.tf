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
    name          = "ec2-subnet"
    ip_cidr_range = "10.40.0.0/24"
    region        = var.region
  }]
}

data "google_client_config" "current" {}

module "ami" {
  source = "../../modules/ami_lookup"
}

module "vm" {
  source       = "../../modules/ec2"
  project_id   = var.project_id
  name         = "dev-compute"
  zone         = var.zone
  machine_type = "e2-medium"
  network      = module.vpc.network_self_link
  subnet       = module.vpc.subnet_self_links[0]
  image        = module.ami.image
  ssh_keys     = ["terraform:${data.google_client_config.current.access_token}"]
}

output "instance" {
  value = module.vm.instance_self_link
}
