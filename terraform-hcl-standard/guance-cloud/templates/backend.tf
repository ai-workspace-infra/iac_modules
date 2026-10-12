# Partial S3-compatible backend (unified state contract). bucket and key are passed
# with -backend-config; endpoint, region and credentials come from the process
# environment (AWS_ENDPOINT_URL_S3, AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
# so no credential is written to .terraform/ or the command line.
terraform {
  backend "s3" {
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
    use_lockfile                = true
    use_path_style              = true
  }
}
