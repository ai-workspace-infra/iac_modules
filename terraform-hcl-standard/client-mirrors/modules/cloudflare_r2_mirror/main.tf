terraform {
  required_version = ">= 1.10"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

data "cloudflare_zone" "this" {
  filter = {
    name = var.zone_name
  }
}

resource "cloudflare_r2_bucket" "this" {
  account_id = var.account_id
  name       = var.bucket_name
  location   = var.location
}

resource "cloudflare_r2_custom_domain" "this" {
  account_id  = var.account_id
  bucket_name = cloudflare_r2_bucket.this.name
  domain      = var.custom_domain
  enabled     = true
  min_tls     = var.min_tls
  zone_id     = data.cloudflare_zone.this.id
}

resource "cloudflare_r2_bucket_cors" "this" {
  account_id  = var.account_id
  bucket_name = cloudflare_r2_bucket.this.name
  rules = [
    {
      id              = "client-mirrors-cors"
      max_age_seconds = var.cors_max_age_seconds
      expose_headers  = ["ETag", "Content-Length", "Content-Type"]
      allowed = {
        methods = var.cors_allowed_methods
        origins = var.cors_allowed_origins
        headers = ["*"]
      }
    }
  ]
}

data "cloudflare_account_api_token_permission_groups_list" "r2_write" {
  account_id = var.account_id
  name       = "Workers R2 Storage Bucket Item Write"
}

resource "cloudflare_account_token" "r2_rw" {
  account_id = var.account_id
  name       = var.token_name
  policies = [
    {
      effect = "allow"
      permission_groups = [
        {
          id = data.cloudflare_account_api_token_permission_groups_list.r2_write.result[0].id
        }
      ]
      resources = jsonencode({
        "com.cloudflare.edge.r2.bucket.${var.account_id}_default_${cloudflare_r2_bucket.this.name}" = "*"
      })
    }
  ]
}
