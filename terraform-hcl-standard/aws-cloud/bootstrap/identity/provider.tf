terraform {
  required_version = ">= 1.2"

  # The production bootstrap workflow supplies this S3-compatible backend at
  # `terraform init` time. Keeping the block empty prevents credentials and
  # endpoints from entering Git while ensuring imports persist beyond a runner.
  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.92"
    }
  }
}

provider "aws" {
  region = local.config_region
}
