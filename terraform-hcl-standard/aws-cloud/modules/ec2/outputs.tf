output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.this.id
}

output "instance_arn" {
  description = "EC2 instance ARN"
  value       = aws_instance.this.arn
}

output "public_ip" {
  description = "Public IPv4 address"
  value       = aws_instance.this.public_ip
}

output "private_ip" {
  description = "Private IPv4 address"
  value       = aws_instance.this.private_ip
}

output "subnet_id" {
  description = "Instance subnet ID"
  value       = aws_instance.this.subnet_id
}

output "vault_agent_iam_role_arn" {
  description = "ARN to bind to a Vault AWS auth role when the optional Vault Agent profile is enabled"
  value       = try(aws_iam_role.vault_agent[0].arn, null)
}

output "vault_agent_iam_instance_profile_name" {
  description = "Name of the optional Vault Agent EC2 instance profile"
  value       = try(aws_iam_instance_profile.vault_agent[0].name, null)
}
