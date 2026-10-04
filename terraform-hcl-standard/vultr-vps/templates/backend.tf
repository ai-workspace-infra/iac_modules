terraform {
  # Backend values are injected only by terraform init from Vault-derived
  # runtime parameters; Terraform backends cannot read normal variables.
  backend "s3" {
    use_lockfile = true
  }
}
