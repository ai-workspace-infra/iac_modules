variable "project_id" {
  description = "Project id"
  type        = string
}

variable "network" {
  description = "Network self link"
  type        = string
}

variable "rules" {
  description = "Firewall rules"
  type = list(object({
    name        = string
    direction   = string
    ranges      = list(string)
    protocols   = map(list(number))
    target_tags = list(string)
  }))
  default = []
}

resource "google_compute_firewall" "rules" {
  for_each = { for rule in var.rules : rule.name => rule }

  name      = each.value.name
  project   = var.project_id
  network   = var.network
  direction = upper(each.value.direction)
  priority  = 1000

  allow = [for proto, ports in each.value.protocols : {
    protocol = proto
    ports    = [for port in ports : tostring(port)]
  }]

  source_ranges      = each.value.direction == "ingress" ? each.value.ranges : null
  destination_ranges = each.value.direction == "egress" ? each.value.ranges : null
  target_tags        = each.value.target_tags
}

output "firewall_rules" {
  value       = [for rule in google_compute_firewall.rules : rule.name]
  description = "Created firewall rules"
}
