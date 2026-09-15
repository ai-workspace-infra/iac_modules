output "instance_self_link" {
  value       = google_compute_instance.this.self_link
  description = "Instance self link"
}

output "instance_id" {
  value       = google_compute_instance.this.instance_id
  description = "Compute Engine numeric instance id"
}

output "private_ip" {
  value       = google_compute_instance.this.network_interface[0].network_ip
  description = "VPC private IPv4 address"
}

output "public_ip" {
  value       = google_compute_instance.this.network_interface[0].access_config[0].nat_ip
  description = "Ephemeral public IPv4 address used for SSH/Ansible"
}
