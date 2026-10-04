locals {
  account  = yamldecode(file(var.account_config_path))
  alb_conf = yamldecode(file(var.alb_config_path))
}

module "alb" {
  source = "../../modules/alb"

  name_prefix = local.alb_conf.name_prefix
  vpc_id      = local.alb_conf.vpc_id
  subnet_ids  = local.alb_conf.subnet_ids
  listeners   = local.alb_conf.listeners

  tags = local.account.tags
}
