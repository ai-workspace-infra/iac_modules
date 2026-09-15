locals {
  bootstrap_config_path = abspath(var.bootstrap_config_path)
  bootstrap = yamldecode(file(local.bootstrap_config_path))

  config_region         = local.bootstrap.region
  config_role_name      = local.bootstrap.iam.role_name
  config_terraform_user = local.bootstrap.iam.terraform_user_name
  environment           = coalesce(try(local.bootstrap.environment, null), try(local.bootstrap.iam.environment, null), "bootstrap")
  extra_tags            = try(local.bootstrap.tags, {})

  create_role        = try(local.bootstrap.iam.create_role, true)
  existing_role_name = try(local.bootstrap.iam.existing_role_name, null)
  existing_role_arn  = try(local.bootstrap.iam.existing_role_arn, null)
  role_name          = coalesce(local.existing_role_name, local.config_role_name)

  create_user         = try(local.bootstrap.iam.create_user, true)
  existing_user_name  = try(local.bootstrap.iam.existing_user_name, null)
  terraform_user_name = coalesce(local.existing_user_name, local.config_terraform_user)

  state_bucket_name   = try(local.bootstrap.state.bucket_name, null)
  lock_table_name     = try(local.bootstrap.state.dynamodb_table_name, null)
  managed_policy_arns = try(local.bootstrap.iam.managed_policy_arns, ["arn:aws:iam::aws:policy/AdministratorAccess"])
}

locals {
  account = {
    account_id  = local.bootstrap.account_id
    environment = local.environment
    tags        = local.extra_tags
  }
}
