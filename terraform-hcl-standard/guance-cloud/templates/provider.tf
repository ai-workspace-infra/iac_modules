terraform {
  required_version = ">= 1.10"
  required_providers {
    guance = {
      source  = "GuanceCloud/guance"
      version = "= 0.1.0"
    }
  }
}

# The management API key is read by the provider from GUANCE_ACCESS_TOKEN
# (documented for GuanceCloud/guance 0.1.0). It is never a Terraform variable.
provider "guance" {
  end_point = var.guance_endpoint
  region    = var.guance_region
}
