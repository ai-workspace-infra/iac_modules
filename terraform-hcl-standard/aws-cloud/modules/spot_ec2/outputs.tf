output "instance_id" {
  value       = aws_instance.this.id
  description = "Temporary EC2 instance ID"
}

output "instance_arn" {
  value = aws_instance.this.arn
}

output "public_ip" {
  value       = aws_instance.this.public_ip
  description = "Temporary EC2 public IPv4"
}

output "private_ip" {
  value       = aws_instance.this.private_ip
  description = "Temporary EC2 private IPv4"
}

output "subnet_id" {
  value = aws_instance.this.subnet_id
}
output "vault_agent_iam_role_arn" {
  description = "ARN to bind to a Vault AWS auth role when the optional Vault Agent profile is enabled"
  value       = try(aws_iam_role.vault_agent[0].arn, null)
}

output "vault_agent_iam_instance_profile_name" {
  description = "Name of the optional Vault Agent EC2 instance profile"
  value       = try(aws_iam_instance_profile.vault_agent[0].name, null)
}
