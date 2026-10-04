locals {
  account = yamldecode(file(var.account_config_path))
  s3_conf = yamldecode(file(var.s3_config_path))
}

module "s3" {
  source = "../../modules/s3"

  bucket_name       = local.s3_conf.bucket_name
  enable_versioning = local.s3_conf.enable_versioning
  tags              = local.account.tags
}
