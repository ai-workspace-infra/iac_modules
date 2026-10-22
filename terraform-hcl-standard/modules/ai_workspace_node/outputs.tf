output "storage_mount_path" {
  description = "Standard persistent storage path on host"
  value       = local.storage_mount_path
}

output "service_domain" {
  description = "Configured public domain for XWorkmate App connection"
  value       = var.domain_name
}

output "ingress_ports" {
  description = "List of permitted ingress ports"
  value       = local.ingress_ports
}
