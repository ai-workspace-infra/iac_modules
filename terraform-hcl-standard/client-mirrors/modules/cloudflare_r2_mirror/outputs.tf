output "bucket" {
  value = cloudflare_r2_bucket.this.name
}

output "custom_domain" {
  value = cloudflare_r2_custom_domain.this.domain
}

output "endpoint" {
  value = "https://${var.account_id}.r2.cloudflarestorage.com"
}

output "access_key_id" {
  value = cloudflare_account_token.r2_rw.id
}

output "secret_access_key" {
  value     = sha256(cloudflare_account_token.r2_rw.value)
  sensitive = true
}
