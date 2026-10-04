output "oidc_provider_arn" {
  description = "IAM OIDC provider ARN."
  value       = aws_iam_openid_connect_provider.this.arn
}

output "role_arn" {
  description = "IAM role ARN trusted by the exact OIDC subject."
  value       = aws_iam_role.this.arn
}
