# 统一多云 IaC State 契约

AWS、GCP、Azure、Vultr VPS 和 Akamai Cloud/Linode 的 Terraform root module
统一使用 S3-compatible backend。云 provider 的认证与 state backend 的认证必须分离：
provider token/identity 只控制云资源；`TF_STATE_*` 只控制 state bucket。

## Vault KV v2

每个环境有一条独立 state 记录：

```text
CLI: vault kv get kv/CICD/<env>/iac_state
API: kv/data/CICD/<env>/iac_state
```

必填字段：

```text
TF_STATE_ENDPOINT
TF_STATE_BUCKET
TF_STATE_ACCESS_KEY
TF_STATE_SECRET_KEY
TF_STATE_REGION
```

这些字段只可由 GitHub OIDC 登录 Vault 后注入 workflow，不得写入 GitOps、
tfvars、Terraform backend 模板或日志。

## Canonical key

Terraform state 的 key 由运行 workflow 生成，固定为：

```text
terraform/<environment>/<project>/<cloud>/<account>/<workspace>/terraform.tfstate
```

同一 state 的 S3 锁为：

```text
terraform/<environment>/<project>/<cloud>/<account>/<workspace>/terraform.tfstate.tflock
```

例如：

```text
terraform/uat/svc.plus/akamai-cloud/primary/ai-workspace/terraform.tfstate
terraform/prod/xworktech/gcp-cloud/xworktech/platform/terraform.tfstate
```

`environment`、`project`、`cloud`、`account` 与 `workspace` 都是 state
边界的一部分；不得以共享 workspace 合并不同账号、环境或资源组。

## Backend and migration

所有模板声明 S3 backend 并启用 `use_lockfile`，因此 runner 使用的 Terraform
版本必须不低于 1.10。backend 的 endpoint、bucket、key、region、access key
与 secret key 仅在 `terraform init -backend-config=...` 时注入。

迁移已有 state 时，先记录旧 key 和新 key，再用 `terraform init -migrate-state`。
迁移后必须执行 `terraform validate` 与无漂移 `terraform plan`；保留原对象的
版本与旧 backend 直到验收完成。

## Non-Terraform platforms

UCloud、Ulighthost 等仅纳管已有资源时不产生 `tfstate`。它们将可公开的资源
事实写入同一 bucket 的下列前缀：

```text
inventory/<environment>/<project>/<cloud>/<account>/<workspace>.json
runs/<environment>/<project>/<cloud>/<account>/<workspace>/<run-id>.json
```

其 GitOps 声明必须设置：

```yaml
management_mode: existing
provisioner: ansible
lifecycle: external
```

external inventory adapter 只能读取、校验和记录已有资源，不得执行 Terraform
或自动创建、销毁资源。
