# Terraform plan/apply for the UAT Guance workspace. Exact paths only; read only.
path "kv/data/uat/platform/observability/guance/xworktech-uat/management" {
  capabilities = ["read"]
}

# One record per notify object declared in GitOps (opt_set JSON: webhook, secret, recipients).
path "kv/data/uat/platform/observability/guance/xworktech-uat/notify/uat_test_receiver" {
  capabilities = ["read"]
}

# Unified state backend record (TF_STATE_*), shared with other UAT IaC roles.
path "kv/data/CICD/uat/iac_state" {
  capabilities = ["read"]
}
