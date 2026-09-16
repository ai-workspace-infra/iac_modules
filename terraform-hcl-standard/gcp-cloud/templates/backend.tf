terraform {
  # The organization-wide S3-compatible state store is injected by CI.
  # Endpoint, bucket, key, credentials and region never live in Git.
  backend "s3" {}
}
