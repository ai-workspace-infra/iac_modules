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
