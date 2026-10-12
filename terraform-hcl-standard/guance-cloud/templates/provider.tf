terraform {
  required_version = ">= 1.5"
  required_providers {
    guance = {
      source  = "GuanceCloud/guance"
      version = "= 0.1.0"
    }
  }
}

provider "guance" {
  access_token = var.guance_api_key
  end_point    = var.guance_endpoint
  region       = var.guance_region
}
