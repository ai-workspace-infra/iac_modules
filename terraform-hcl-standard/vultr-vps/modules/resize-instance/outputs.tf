output "instance_id" {
  description = "Replacement instance ID."
  value       = vultr_instance.replacement.id
}

output "main_ip" {
  description = "Replacement public IPv4 address."
  value       = vultr_instance.replacement.main_ip
}

output "label" {
  description = "Replacement instance label."
  value       = vultr_instance.replacement.label
}

output "plan" {
  description = "Replacement plan."
  value       = vultr_instance.replacement.plan
}
