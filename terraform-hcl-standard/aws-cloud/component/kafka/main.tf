locals {
  account    = yamldecode(file(var.account_config_path))
  kafka_conf = yamldecode(file(var.kafka_config_path))
}

module "kafka" {
  source = "../../modules/msk"

  name_prefix   = local.kafka_conf.name_prefix
  kafka_version = local.kafka_conf.kafka_version

  instance_type          = local.kafka_conf.brokers.instance_type
  number_of_broker_nodes = local.kafka_conf.brokers.number_of_broker_nodes

  volume_size = local.kafka_conf.ebs.volume_size

  vpc_id     = local.kafka_conf.vpc_id
  subnet_ids = local.kafka_conf.subnet_ids

  tags = local.account.tags
}
