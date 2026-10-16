terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "asia-east1"
}

variable "network_name" {
  type = string
}

variable "subnet_cidr" {
  type    = string
  default = "10.60.0.0/20"
}

variable "subnet_name" {
  type        = string
  default     = ""
  description = "Explicit subnetwork name override."
}

variable "private_ip_google_access" {
  type        = bool
  default     = true
  description = "Whether VMs on this subnetwork can access Google services without external IP."
}

variable "enable_nat" {
  type        = bool
  default     = true
  description = "Whether to create Cloud Router and Cloud NAT for subnet egress."
}

variable "create_network" {
  type        = bool
  default     = true
  description = "Whether to create a new VPC network. If false, look up existing network_name."
}

# Preserve states created before Cloud NAT became optional and these resources
# gained count-based addresses.
moved {
  from = google_compute_network.this
  to   = google_compute_network.this[0]
}

moved {
  from = google_compute_router.this
  to   = google_compute_router.this[0]
}

moved {
  from = google_compute_router_nat.this
  to   = google_compute_router_nat.this[0]
}

data "google_compute_network" "this" {
  count   = var.create_network ? 0 : 1
  project = var.project_id
  name    = var.network_name
}

resource "google_compute_network" "this" {
  count                   = var.create_network ? 1 : 0
  project                 = var.project_id
  name                    = var.network_name
  auto_create_subnetworks = false
}

locals {
  network_id        = var.create_network ? google_compute_network.this[0].id : data.google_compute_network.this[0].id
  network_self_link = var.create_network ? google_compute_network.this[0].self_link : data.google_compute_network.this[0].self_link
}

resource "google_compute_subnetwork" "this" {
  project                  = var.project_id
  name                     = var.subnet_name != "" ? var.subnet_name : "${var.network_name}-subnet"
  region                   = var.region
  network                  = local.network_id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = var.private_ip_google_access
}

resource "google_compute_router" "this" {
  count   = var.enable_nat ? 1 : 0
  project = var.project_id
  name    = "${var.network_name}-router"
  region  = var.region
  network = local.network_id
}

resource "google_compute_address" "nat" {
  count        = var.enable_nat ? 1 : 0
  project      = var.project_id
  name         = "${var.network_name}-nat-ip"
  region       = var.region
  address_type = "EXTERNAL"
  network_tier = "PREMIUM"
}

resource "google_compute_router_nat" "this" {
  count                              = var.enable_nat ? 1 : 0
  project                            = var.project_id
  name                               = "${var.network_name}-nat"
  router                             = google_compute_router.this[0].name
  region                             = var.region
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.nat[0].self_link]
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.this.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }
}

output "network" {
  value = local.network_self_link
}

output "subnet" {
  value = google_compute_subnetwork.this.self_link
}

output "nat_ip" {
  value = var.enable_nat ? google_compute_address.nat[0].address : null
}
