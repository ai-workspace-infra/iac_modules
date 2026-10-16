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
  value       = var.elastic_ip ? aws_eip.this[0].public_ip : aws_instance.this.public_ip
}

output "private_ip" {
  description = "Private IPv4 address"
  value       = aws_instance.this.private_ip
}

output "subnet_id" {
  description = "Instance subnet ID"
  value       = aws_instance.this.subnet_id
}
