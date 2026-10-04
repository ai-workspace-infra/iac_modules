variable "project_id" {
  description = "Project id"
  type        = string
}

variable "name" {
  description = "Load balancer name"
  type        = string
  default     = "tcp-lb"
}

variable "network" {
  description = "Network self link"
  type        = string
}

variable "subnet" {
  description = "Subnetwork self link"
  type        = string
}

variable "port" {
  description = "Service port"
  type        = number
  default     = 80
}

variable "zone" {
  description = "Zone for unmanaged instance group"
  type        = string
  default     = "us-central1-a"
}

resource "google_compute_instance_group" "placeholder" {
  name    = "${var.name}-ig"
  project = var.project_id
  zone    = var.zone
  network = var.network
  named_port {
    name = "service"
    port = var.port
  }
}

resource "google_compute_health_check" "tcp" {
  name    = "${var.name}-hc"
  project = var.project_id
  tcp_health_check {
    port = var.port
  }
}

resource "google_compute_backend_service" "tcp" {
  name                  = "${var.name}-backend"
  project               = var.project_id
  load_balancing_scheme = "EXTERNAL"
  protocol              = "TCP"
  health_checks         = [google_compute_health_check.tcp.self_link]
  backend {
    group = google_compute_instance_group.placeholder.self_link
  }
}

resource "google_compute_forwarding_rule" "tcp" {
  name                  = "${var.name}-fwd"
  project               = var.project_id
  load_balancing_scheme = "EXTERNAL"
  ip_protocol           = "TCP"
  port_range            = tostring(var.port)
  backend_service       = google_compute_backend_service.tcp.self_link
  network               = var.network
  subnetwork            = var.subnet
}

output "forwarding_rule" {
  value       = google_compute_forwarding_rule.tcp.name
  description = "TCP forwarding rule"
}
