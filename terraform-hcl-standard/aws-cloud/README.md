# Terraform Bootstrap for S3 Backend & DynamoDB Lock Table

This repository provides bootstrap Terraform modules that must be applied before enabling a Terraform remote backend on AWS.
It creates:
- IAM artifacts — a deploy role plus a dedicated DevOps/automation user for Terraform
- S3 bucket — to store Terraform remote state
- DynamoDB table — to store Terraform state locks

Both modules can be run independently.

- bootstrap/state/        # S3 state bucket (versioning + SSE)
- bootstrap/lock/         # DynamoDB lock table (LockID)
- bootstrap/identity/     # IAM roles, policies and bootstrap users

---
** Note: S3 bucket must be emptied before deletion. **

## Config Source of Truth (GitOps)

All AWS config YAML now lives in the external GitOps repo:

```
https://github.com/ai-workspace-infra/gitops.git
```

Clone it next to this repo and export `GITOPS_ROOT` for scripts that consume declarations:

```
git clone https://github.com/ai-workspace-infra/gitops.git ../gitops
export GITOPS_ROOT="$(cd ../gitops && pwd)"
```

## 1. AWS Credentials Setup

Terraform reads AWS credentials through the standard AWS credential chain. You may use either A or B.

If your shell or CI job is **already running under the target IAM role**, set
`AWS_CLOUD_SKIP_ASSUME_ROLE=true` before rendering/running Terraform to avoid a
nested `AssumeRole` call:

```
export AWS_CLOUD_SKIP_ASSUME_ROLE=true
```

This prevents errors like `AccessDenied` when re-assuming the same deploy role.

### A. Environment Variables (recommended for local / CI)

```
export AWS_ACCESS_KEY_ID="AKIAxxxxxxxxxxxx"
export AWS_SECRET_ACCESS_KEY="xxxxxxxxxxxxxxxx"
export AWS_DEFAULT_REGION="ap-northeast-1"
```

Terraform will automatically detect them.

### B. AWS CLI Credentials File (~/.aws/credentials)

- Run: aws configure
- Credentials file: ~/.aws/credentials

```
Example:
[default]
aws_access_key_id     = AKIAxxxxxxxxxxxx
aws_secret_access_key = xxxxxxxxxxxxxxxxx
region                = ap-northeast-1
```

Select profile if needed: export AWS_PROFILE=default

## 2. Bootstrap: Create S3 Bucket

```
cd bootstrap/state
terraform init
terraform apply \
  -var="bucket_name=svc-plus-iac-state" \
  -var="region=ap-northeast-1"
```

This creates: 
- S3 bucket for Terraform state
- Versioning enabled
- Server-side encryption (AES256) enabled

## 3. Bootstrap: Create DynamoDB Lock Table

```
cd bootstrap/lock
terraform init
terraform plan \
  -var="region=ap-northeast-1" \
  -var="table_name=svc-plus-iac-state-dynamodb-lock"
terraform apply \
  -var="region=ap-northeast-1" \
  -var="table_name=svc-plus-iac-state-dynamodb-lock"
terraform output
```

This creates: 

- DynamoDB table: terraform-locks
- Primary key: LockID

PAY_PER_REQUEST billing mode Compatible with Terraform backend locking

## 4. Bootstrap IAM Role

```
cd bootstrap/identity
terraform init
terraform apply \
  -var="account_name=dev" \
  -var="role_name=TerraformDeployRole-Dev"

By default the deploy role attaches the AWS managed **AdministratorAccess** policy so
subsequent Terraform runs can create infrastructure resources (e.g., VPCs, EIPs). You
can override this by passing `-var='managed_policy_arns=["arn:aws:iam::aws:policy/PowerUserAccess"]'`
or another list of managed policy ARNs when tighter permissions are required.
```

## 5. Use in Terraform Backend

After both bootstrap steps are completed:

terraform {
  backend "s3" {
    bucket         = "my-terraform-state"
    key            = "envs/dev/terraform.tfstate"
    region         = "ap-northeast-1"
    encrypt        = true
    dynamodb_table = "terraform-locks"
  }
}

Then run:

terraform init -migrate-state

## Multi-region production Agent Proxy

The production Agent Proxy declaration keeps the stable Tokyo node on the
default `aws` provider and declares the ephemeral US node with the explicit
`aws.us` provider alias. Both hosts use `t4g.micro` (2 vCPU / 1 GiB); Tokyo is
on-demand and continuously running with its existing EIP, while US is a
one-time Spot request with a 60-minute self-termination timer and no EIP.

The regional topology is declared in
`config/resources/prod/agent-proxy.yaml`. `generate.py` renders one explicit
provider-scoped data/resource/module set per host, then `generate.py inventory`
publishes both hosts to the CMDB. The deployment workflow uses each CMDB host
key as `AGENT_PROXY_DOMAIN`, so Caddy and Xray do not share a hard-coded
hostname across regional nodes. The public names are
`agent-proxy-selfhost-prod-jp.<zone>` and `agent-proxy-selfhost-prod-us.<zone>`;
the Tokyo resource and its existing EIP remain unchanged.

### Short node identity

Each Agent Proxy declaration also carries a compact operator-facing identity:

| Node | `node_id` / `short_hostname` | `node_label` | Region | Billing |
| --- | --- | --- | --- | --- |
| Tokyo primary | `ap-prod-tky` | `tky-on-demand` | `ap-northeast-1` | on-demand |
| US edge | `ap-prod-us` | `us-spot` | `us-east-1` | Spot, 60 min |

`display_name` is emitted to CMDB as the concise form (for example,
`ap-prod-us (us-spot)`). These fields are also exposed through Ansible
hostvars. The public service FQDNs remain unchanged so existing subscriptions
and DNS records are not invalidated; the compact names are for AWS console,
CMDB, dashboards, and operator lists.

## Security Notes

Never store AWS credentials in Terraform variables
Never commit credentials to Git

Prefer:

- environment variables
- AWS CLI profiles
- IAM Role / SSO / OIDC (recommended)
- S3 bucket has: Versioning ON

Server-side encryption ON

## 6. Cleanup

To remove bootstrap resources:

terraform destroy

Resource names (bucket, DynamoDB table, IAM role/user) are defined in the GitOps bootstrap declaration. Set `CONFIG_PATH` to that file before tearing down the S3 backend:

```
aws s3 rb "s3://$(python -c "import os,yaml;print(yaml.safe_load(open(os.environ['CONFIG_PATH']))['state']['bucket_name'])")" --force
```


# Access Key + STS 的执行流程（内部机制）

你的 Terraform 执行流程变成：

Terraform 读取你的 Access Key
→ 用 GET CALLER IDENTITY 验证身份
调用 sts:AssumeRole
获得临时凭证（Session Token）
Terraform 使用临时凭证执行所有资源创建

AccessKey → STS → AssumeRole → 临时 Token → Terraform apply
