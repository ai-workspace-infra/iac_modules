# Non-secret workspace variables rendered into terraform.auto.tfvars.json
# from gitops/resources/<project>/<env>/client-mirrors/mirrors.yaml.
# CLOUDFLARE_API_TOKEN, ALICLOUD_ACCESS_KEY, ALICLOUD_SECRET_KEY, and
# TF_VAR_cloudflare_account_id come from Vault/env at runtime.

variable "cloudflare_account_id" {
  description = "Cloudflare Account ID loaded from Vault (kv/prod/serverless/cloudflare -> CLOUDFLARE_ACCOUNT_ID)."
  type        = string
}

variable "alicloud_region" {
  description = "Default Alicloud provider region matching the OSS mirror region."
  type        = string
}

variable "zone_name" {
  description = "Primary DNS zone managed in Cloudflare (e.g. svc.plus)."
  type        = string
}
