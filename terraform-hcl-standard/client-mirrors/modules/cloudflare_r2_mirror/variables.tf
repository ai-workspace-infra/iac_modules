variable "account_id" {
  description = "Cloudflare Account ID owning the R2 bucket."
  type        = string
}

variable "zone_name" {
  description = "Cloudflare DNS zone name for the custom domain (e.g. svc.plus)."
  type        = string
}

variable "bucket_name" {
  description = "Cloudflare R2 bucket name."
  type        = string
}

variable "custom_domain" {
  description = "Public custom domain attached to the R2 bucket (e.g. dl.svc.plus)."
  type        = string
}

variable "location" {
  description = "Preferred R2 location hint (apac, eeur, enam, weur, wnam, oc)."
  type        = string
  default     = "apac"
}

variable "min_tls" {
  description = "Minimum TLS version accepted on the R2 custom domain."
  type        = string
  default     = "1.2"
}

variable "cors_allowed_origins" {
  description = "Allowed CORS origins for browser/Portal reads."
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

variable "token_name" {
  description = "Name of the bucket-scoped Cloudflare Account API token for R2 S3 sync."
  type        = string
}
