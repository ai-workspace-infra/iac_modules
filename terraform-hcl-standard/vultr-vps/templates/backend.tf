terraform {
  backend "s3" {
    endpoints = {
      s3 = var.object_storage_endpoint
    }
    bucket                      = var.state_bucket
    key                         = var.state_key
    region                      = var.region
    access_key                  = var.access_key
    secret_key                  = var.secret_key
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
    force_path_style            = true
  }
}

variable "object_storage_endpoint" {
  description = "Vultr 对象存储的 S3 兼容 Endpoint (例如 https://ewr1.vultrobjects.com)"
  type        = string
}

variable "state_bucket" {
  description = "用于存储 Terraform state 的对象存储桶"
  type        = string
}

variable "state_key" {
  description = "state 文件路径，例如 vpc/dev/terraform.tfstate"
  type        = string
}

variable "region" {
  description = "Vultr 区域代码，例如 ewr、sgp、fra"
  type        = string
}

variable "access_key" {
  description = "对象存储访问密钥 Access Key"
  type        = string
  sensitive   = true
}

variable "secret_key" {
  description = "对象存储访问密钥 Secret Key"
  type        = string
  sensitive   = true
}
