include "root" {
  path = find_in_parent_folders()
}

dependencies {
  paths = ["../state", "../lock"]
}

terraform {
  source = "${get_parent_terragrunt_dir()}/..//bootstrap/identity"
}

inputs = {
  bootstrap_config_path = coalesce(
    trimspace(get_env("BOOTSTRAP_CONFIG_PATH", "")),
    null
  )
  github_actions_oidc_config_path = coalesce(
    trimspace(get_env("GITHUB_ACTIONS_OIDC_CONFIG_PATH", "")),
    null
  )
}
