terraform {
  required_version = ">= 1.10"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
    alicloud = {
      source  = "aliyun/alicloud"
      version = ">= 1.210.0"
    }
  }
}

# Credentials come from standard provider environment variables only:
#   CLOUDFLARE_API_TOKEN, ALICLOUD_ACCESS_KEY, ALICLOUD_SECRET_KEY.
provider "cloudflare" {}

provider "alicloud" {
  region = var.alicloud_region
}
