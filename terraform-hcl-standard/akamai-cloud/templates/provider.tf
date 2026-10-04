terraform {
  required_version = ">= 1.10"

  required_providers {
    linode = {
      source  = "linode/linode"
      version = "~> 4.5"
    }
  }
}

provider "linode" {
  token = var.linode_token
}

variable "linode_token" {
  description = "Akamai Cloud/Linode API token，建议通过 LINODE_TOKEN 提供"
  type        = string
  sensitive   = true
}
