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

variable "enable_nat" {
  type        = bool
  default     = true
  description = "Whether to create Cloud Router and Cloud NAT for subnet egress."
}

# Preserve states created before Cloud NAT became optional and these resources
# gained count-based addresses.
moved {
  from = google_compute_router.this
  to   = google_compute_router.this[0]
}

moved {
  from = google_compute_router_nat.this
  to   = google_compute_router_nat.this[0]
}

resource "google_compute_network" "this" {
  project                 = var.project_id
  name                    = var.network_name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "this" {
  project                  = var.project_id
  name                     = "${var.network_name}-subnet"
  region                   = var.region
  network                  = google_compute_network.this.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true
}

resource "google_compute_router" "this" {
  count   = var.enable_nat ? 1 : 0
  project = var.project_id
  name    = "${var.network_name}-router"
  region  = var.region
  network = google_compute_network.this.id
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
  value = google_compute_network.this.self_link
}

output "subnet" {
  value = google_compute_subnetwork.this.self_link
}

output "nat_ip" {
  value = var.enable_nat ? google_compute_address.nat[0].address : null
}
