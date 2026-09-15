locals {
  account  = yamldecode(file(var.account_config_path))
  nlb_conf = yamldecode(file(var.nlb_config_path))
}

module "nlb" {
  source = "../../modules/nlb"

  name_prefix = local.nlb_conf.name_prefix
  vpc_id      = local.nlb_conf.vpc_id
  subnet_ids  = local.nlb_conf.subnet_ids
  listeners   = local.nlb_conf.listeners

  tags = local.account.tags
}
