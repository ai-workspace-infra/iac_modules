locals {
  config_files = var.config_files

  account = yamldecode(file(local.config_files[0]))

  vpc_conf = yamldecode(file(local.config_files[1]))
}

module "vpc" {
  source = "../../modules/vpc"

  vpc_cidr        = local.vpc_conf.vpc_cidr
  public_subnets  = local.vpc_conf.public_subnets
  private_subnets = local.vpc_conf.private_subnets
  name_prefix     = local.vpc_conf.name_prefix

  tags = local.account.tags
}
