variable "cloudflare_zone_name" {
  description = "Cloudflare zone hosting the DNS CNAME for the Aliyun CDN domain."
  type        = string
}

variable "bucket_name" {
  description = "Aliyun OSS bucket name."
  type        = string
}

variable "oss_region" {
  description = "Aliyun OSS region slug without 'oss-' prefix (e.g. cn-hongkong)."
  type        = string
}

variable "oss_acl" {
  description = "Aliyun OSS bucket ACL (public-read or private)."
  type        = string
  default     = "public-read"
}

variable "cdn_domain" {
  description = "Aliyun CDN accelerated domain (e.g. cn-dl.svc.plus)."
  type        = string
}

variable "cdn_type" {
  description = "Aliyun CDN business type (download, web, video)."
  type        = string
  default     = "download"
}

variable "cdn_scope" {
  description = "Aliyun CDN acceleration scope (overseas, domestic, global)."
  type        = string
  default     = "overseas"
}

variable "cdn_rate_limit" {
  description = "Aliyun CDN per-request download rate limit (e.g. 10m)."
  type        = string
  default     = "10m"
}

variable "cdn_rate_limit_after" {
  description = "Aliyun CDN response size threshold before rate limit applies (e.g. 1m)."
  type        = string
  default     = "1m"
}

variable "cors_allowed_origins" {
  description = "Allowed CORS origins for Portal/browser reads."
  type        = list(string)
}

variable "cors_allowed_methods" {
  description = "Allowed CORS HTTP methods."
  type        = list(string)
  default     = ["GET", "HEAD"]
}

variable "cors_max_age_seconds" {
  description = "CORS preflight cache TTL in seconds."
  type        = number
  default     = 3600
}

variable "ram_user_name" {
  description = "RAM username created for least-privilege OSS publishing."
  type        = string
}

variable "ram_policy_name" {
  description = "Custom RAM policy name attached to the OSS publisher user."
  type        = string
}
