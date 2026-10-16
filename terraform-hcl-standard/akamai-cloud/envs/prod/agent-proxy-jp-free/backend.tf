terraform {
  backend "s3" {
    endpoints                   = { s3 = "https://s3.us-east-1.amazonaws.com" }
    region                      = "us-east-1"
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
    use_path_style              = true
    use_lockfile                = true
    workspace_key_prefix        = "env"
  }
}
