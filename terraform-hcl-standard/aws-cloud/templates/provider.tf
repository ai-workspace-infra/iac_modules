terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# The production Agent Proxy pool spans the existing Tokyo node and a
# short-lived US Spot node. Keep the provider aliases explicit so each host's
# region is selected from the resource declaration rather than from runner
# state or an ambient AWS_DEFAULT_REGION.
provider "aws" {
  alias  = "us"
  region = var.aws_us_region
}

provider "aws" {
  alias  = "hk"
  region = var.aws_hk_region
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "ap-northeast-1"
}

variable "aws_us_region" {
  description = "AWS region for the US Agent Proxy provider alias"
  type        = string
  default     = "us-east-1"
}

variable "aws_hk_region" {
  description = "AWS region for the Hong Kong Agent Proxy provider alias"
  type        = string
  default     = "ap-east-1"
}
