# Terraform state backend

This bootstrap configuration uses the organization-wide S3-compatible state
store. The workflow supplies `endpoint`, `bucket`, `key`, `access_key`,
`secret_key`, and `region` from Vault's `CICD` KV record at runtime.

Do not add a GCS backend, a service-account JSON key, or long-lived GCP
credentials to this module.
