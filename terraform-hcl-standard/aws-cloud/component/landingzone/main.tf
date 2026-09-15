locals {
  account = yamldecode(file(var.account_config_path))
}

module "landingzone" {
  source = "../../modules/landingzone"

  region               = local.account.region
  account_id           = local.account.account_id
  console_mode         = local.account.landingzone.console_mode
  enable_risp_controls = local.account.landingzone.enable_risp_controls
  enable_root_limited  = local.account.landingzone.enable_root_limited
  enable_mfa_enforce   = local.account.landingzone.enable_mfa_enforce
}
