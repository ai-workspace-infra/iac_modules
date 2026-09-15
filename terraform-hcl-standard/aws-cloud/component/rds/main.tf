locals {
  account  = yamldecode(file(var.account_config_path))
  rds_conf = yamldecode(file(var.rds_config_path))
}

module "rds" {
  source = "../../modules/rds"

  name_prefix    = local.rds_conf.name_prefix
  engine         = local.rds_conf.engine
  engine_version = local.rds_conf.engine_version
  instance_class = local.rds_conf.instance_class

  username = local.rds_conf.username
  password = local.rds_conf.password

  allocated_storage     = local.rds_conf.allocated_storage
  max_allocated_storage = local.rds_conf.max_allocated_storage

  multi_az            = local.rds_conf.multi_az
  publicly_accessible = local.rds_conf.publicly_accessible

  subnet_ids             = local.rds_conf.subnet_ids
  vpc_security_group_ids = local.rds_conf.vpc_security_group_ids

  parameters = local.rds_conf.parameters

  tags = merge(local.account.tags, local.rds_conf.tags)
}
