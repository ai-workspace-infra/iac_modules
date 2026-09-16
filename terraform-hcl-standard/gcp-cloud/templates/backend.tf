terraform {
  # Connection parameters and the canonical key are injected by the CI
  # backend config file. They must never be rendered into GitOps or tfvars.
  backend "s3" {
    use_lockfile = true
  }
}
