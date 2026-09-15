locals {
  account = yamldecode(file(var.account_config_path))
  redis   = yamldecode(file(var.redis_config_path))
}

module "redis" {
  source = "../../modules/redis"

  name_prefix        = local.redis.name_prefix
  engine_version     = local.redis.engine_version
  node_type          = local.redis.node_type
  num_cache_nodes    = local.redis.num_cache_nodes
  subnet_ids         = local.redis.subnet_ids
  security_group_ids = local.redis.security_group_ids
  tags               = local.account.tags
}
