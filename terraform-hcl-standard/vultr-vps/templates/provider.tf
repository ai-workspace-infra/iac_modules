terraform {
  required_version = ">= 1.10"

  required_providers {
    vultr = {
      source  = "vultr/vultr"
      version = "~> 2.19"
    }
  }
}

provider "vultr" {
  api_key    = var.vultr_api_key
  rate_limit = 700
}

variable "vultr_api_key" {
  description = "Vultr API Key，建议通过环境变量 VULTR_API_KEY 提供"
  type        = string
  sensitive   = true
}
