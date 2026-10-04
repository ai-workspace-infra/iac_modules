terraform {
  # All clouds share the organization S3-compatible state service. Supply
  # endpoint, bucket, key and credentials only through terraform init.
  backend "s3" {
    use_lockfile = true
  }
}
