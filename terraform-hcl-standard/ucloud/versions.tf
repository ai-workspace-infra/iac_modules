terraform {
  required_version = ">= 1.5.0"

  required_providers {
    ucloud = {
      source  = "ucloud/ucloud"
      version = "~> 1.39.0"
    }
  }
}
