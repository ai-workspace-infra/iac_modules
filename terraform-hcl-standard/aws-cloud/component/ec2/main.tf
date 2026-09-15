locals {
  account  = yamldecode(file(var.account_config_path))
  ec2_conf = yamldecode(file(var.ec2_config_path))
}

module "ami_lookup" {
  source = "../../modules/ami_lookup"
  name   = local.ec2_conf.instance.ami
  region = local.account.region
}

module "keypair" {
  source     = "../../modules/keypair"
  name       = local.ec2_conf.keypair.name
  public_key = local.ec2_conf.keypair.public_key
  tags       = local.account.tags
}

module "sg" {
  source = "../../modules/sg"

  name               = local.ec2_conf.security_group.name
  vpc_id             = local.ec2_conf.vpc_id # <<<<<< 来自 YAML
  ssh_cidr           = local.ec2_conf.security_group.ssh_cidr
  additional_ingress = local.ec2_conf.security_group.additional_ingress
  tags               = local.account.tags
}

module "ec2" {
  source = "../../modules/ec2"

  name_prefix = local.ec2_conf.name_prefix
  instance = {
    type = local.ec2_conf.instance.type
    ami  = module.ami_lookup.id # <<<<<< 自动解析 AMI
  }
  subnet_id    = local.ec2_conf.subnet_id # <<<<<< 来自 YAML
  sg_id        = module.sg.sg_id
  keypair_name = module.keypair.keypair_name
  tags         = local.account.tags
}
