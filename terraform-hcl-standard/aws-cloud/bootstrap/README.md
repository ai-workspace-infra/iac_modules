# AWS Bootstrap (Terraform + Terragrunt)

This bootstrap stack provisions the shared primitives required for Terraform automation on AWS using the **terraform-hcl-standard** baseline. It delivers an auditable, deterministic foundation that can be reused across environments.

## Architecture

- **state**: Versioned, SSE-encrypted S3 bucket with public access blocked for Terraform state storage.
- **lock**: DynamoDB table with point-in-time recovery (PITR) and server-side encryption for state locking and auditability.
- **identity**: Terraform deploy role plus automation user, wired with least-privilege inline policies stored as external JSON documents.
- **Orchestration**: Terragrunt dependencies guarantee the apply order (state → lock → identity) and propagate outputs (bucket name, region, lock table) automatically.

## Execution Order

1. `state`: Creates the S3 backend bucket and exports `bucket_name`, `bucket_arn`, and `region`.
2. `lock`: Creates the DynamoDB lock table in the same region and exports `dynamodb_table_name` and `region`.
3. `identity`: Uses dependency outputs to bind IAM policies to the created state and lock resources.

Terragrunt `run-all` handles the ordering; no manual sequencing is required.

## Security Model

- **Data plane**: S3 bucket enforces AES256 SSE, public access block, and versioning. DynamoDB enables server-side encryption and PITR for forensic recovery.
- **Control plane**: IAM policies are externalized in `identity/policies/*.json` and rendered via `aws_iam_policy_document` to keep Terraform code lean and auditable.
- **Config source of truth**: Account/environment bootstrap YAML is read from the sibling GitOps repository. Pass its absolute path with `BOOTSTRAP_CONFIG_PATH`; the bootstrap modules do not fall back to a copy under `iac_modules`.

For the production identity bootstrap, clone GitOps next to this repository and
set the paths explicitly:

```bash
export GITOPS_ROOT="$(cd ../../../../gitops && pwd)"
export BOOTSTRAP_CONFIG_PATH="$GITOPS_ROOT/resources/svc.plus/prod/aws/bootstrap-identity.yaml"
export GITHUB_ACTIONS_OIDC_CONFIG_PATH="$GITOPS_ROOT/resources/svc.plus/prod/aws/github-actions-oidc.json"
```

Generic AWS resource renders also take their inputs from GitOps. For example,
UAT AI Aggregator uses
`$GITOPS_ROOT/resources/svc.plus/uat/aws/ai-aggregator.yaml`.

## How to Run with Terragrunt

```bash
cd terraform-hcl-standard/aws-cloud/bootstrap

# Plan everything in dependency order
terragrunt run-all plan

# Apply everything (state -> lock -> identity)
terragrunt run-all apply
```

### Targeting a Single Module

```bash
terragrunt plan --terragrunt-working-dir state
terragrunt apply --terragrunt-working-dir identity
```

Terragrunt injects dependency outputs automatically; you do not need to pass bucket or table names manually.

### Decommissioning Bootstrap Resources

Bootstrap is intentionally outside day-to-day state management. Avoid `terragrunt destroy` and use the AWS CLI for teardown to keep lifecycle control explicit and auditable.

```bash
# Remove automation user and deploy role (customize to your account IDs)
aws iam delete-access-key --user-name terraform-automation --access-key-id <key-id>
aws iam delete-user-policy --user-name terraform-automation --policy-name terraform-automation-inline
aws iam delete-user --user-name terraform-automation
aws iam detach-role-policy --role-name terraform-deploy --policy-arn arn:aws:iam::<account-id>:policy/terraform-deploy-inline
aws iam delete-role --role-name terraform-deploy

# Remove lock + state once no stacks depend on them
aws dynamodb delete-table --table-name <bootstrap-lock-table>
aws s3 rb s3://<bootstrap-state-bucket> --force
```

Document the teardown in your change log for auditability.

## CloudNeutral Bootstrap Principles

- **Separation of concerns**: State, locking, and identity are isolated modules with explicit interfaces.
- **Least privilege by default**: IAM policies grant the minimal scope required for bootstrap lifecycle operations.
- **Idempotent automation**: All configurations are declarative, version-controlled, and runnable via Terragrunt without manual steps.
- **Auditability**: Policies live in external JSON files; DynamoDB PITR and S3 versioning preserve history for compliance.
- **Portability**: Inputs are read from YAML configuration and Terragrunt dependencies, making the stack reusable across accounts and regions.

Optional YAML fields supported by the bootstrap modules:

```yaml
state:
  create_bucket: true
iam:
  create_role: true
  existing_role_name: null
  existing_role_arn: null
  create_user: true
  existing_user_name: null
  managed_policy_arns:
    - arn:aws:iam::aws:policy/AdministratorAccess
```
