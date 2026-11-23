terraform {
  required_version = ">= 1.10"

  required_providers {
    alicloud = {
      source  = "aliyun/alicloud"
      version = ">= 1.210.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

resource "alicloud_oss_bucket" "this" {
  bucket = var.bucket_name

  versioning {
    status = "Enabled"
  }

  server_side_encryption_rule {
    sse_algorithm = "AES256"
  }

  lifecycle {
    ignore_changes = [cors_rule]
  }
}

resource "alicloud_oss_bucket_acl" "this" {
  bucket = alicloud_oss_bucket.this.bucket
  acl    = var.oss_acl
}

resource "alicloud_oss_bucket_cors" "this" {
  bucket        = alicloud_oss_bucket.this.bucket
  response_vary = true

  cors_rule {
    allowed_methods = var.cors_allowed_methods
    allowed_origins = var.cors_allowed_origins
    allowed_headers = ["*"]
    expose_header   = ["ETag", "Content-Length", "Content-Type"]
    max_age_seconds = var.cors_max_age_seconds
  }
}

resource "alicloud_cdn_domain_new" "this" {
  domain_name = var.cdn_domain
  cdn_type    = var.cdn_type
  scope       = var.cdn_scope

  sources {
    content  = "${alicloud_oss_bucket.this.bucket}.oss-${var.oss_region}.aliyuncs.com"
    type     = "oss"
    port     = 80
    priority = 20
    weight   = 10
  }
}

resource "alicloud_cdn_domain_config" "limit_rate" {
  domain_name   = alicloud_cdn_domain_new.this.domain_name
  function_name = "limit_rate"

  function_args {
    arg_name  = "ali_limit_rate"
    arg_value = var.cdn_rate_limit
  }

  function_args {
    arg_name  = "ali_limit_rate_after"
    arg_value = var.cdn_rate_limit_after
  }
}

data "cloudflare_zone" "this" {
  filter = {
    name = var.cloudflare_zone_name
  }
}

resource "cloudflare_dns_record" "cdn_cname" {
  zone_id = data.cloudflare_zone.this.id
  name    = var.cdn_domain
  type    = "CNAME"
  content = alicloud_cdn_domain_new.this.cname
  proxied = false
  ttl     = 300
  comment = "Managed by iac_modules client-mirrors (Aliyun CDN origin CNAME)"
}

resource "alicloud_ram_user" "ci_rw" {
  name         = var.ram_user_name
  display_name = "CI Client Mirrors OSS Publisher"
  comments     = "Least-privilege CI publisher for releases/* and offline-package/* prefixes"
  force        = true
}

resource "alicloud_ram_policy" "ci_rw" {
  policy_name = var.ram_policy_name
  description = "Least-privilege OSS object R/W scoped to release prefixes for client mirror bucket."
  force       = true
  policy_document = jsonencode({
    Version = "1"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "oss:PutObject",
          "oss:GetObject",
          "oss:DeleteObject",
          "oss:AbortMultipartUpload",
          "oss:ListMultipartUploads",
          "oss:ListParts",
        ]
        Resource = [
          "acs:oss:*:*:${alicloud_oss_bucket.this.bucket}/releases/*",
          "acs:oss:*:*:${alicloud_oss_bucket.this.bucket}/offline-package/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "oss:GetBucketInfo",
          "oss:ListObjects",
        ]
        Resource = [
          "acs:oss:*:*:${alicloud_oss_bucket.this.bucket}",
        ]
        Condition = {
          StringLike = {
            "oss:Prefix" = [
              "releases/*",
              "offline-package/*",
            ]
          }
        }
      },
    ]
  })
}

resource "alicloud_ram_user_policy_attachment" "ci_rw" {
  policy_name = alicloud_ram_policy.ci_rw.policy_name
  policy_type = alicloud_ram_policy.ci_rw.type
  user_name   = alicloud_ram_user.ci_rw.name
}

resource "alicloud_ram_access_key" "ci_rw" {
  user_name = alicloud_ram_user.ci_rw.name
}
