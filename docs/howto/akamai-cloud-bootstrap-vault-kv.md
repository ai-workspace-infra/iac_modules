# Akamai Cloud / Linode VPS Bootstrap How-to

本文说明 Akamai Cloud/Linode VPS 接入本仓库的首次 bootstrap、Terraform 远端
state 和 Vault KV v2 契约。本文只管理云基础设施凭据和 state 连接信息；VPS
拓扑仍由 GitOps 的 `resources/<project>/<env>/akamai/*.yaml` 声明。

## 1. 组件边界

本方案使用官方 `linode/linode` Terraform provider：

| 能力 | 实现 |
| --- | --- |
| VPS/compute | `linode_instance` |
| SSH key | `linode_sshkey` |
| 防火墙 | `linode_firewall` |
| VPC | `linode_vpc` + `linode_vpc_subnet` |
| 块存储 | `linode_volume` |
| Terraform state | Akamai Object Storage，S3-compatible |
| Edge/CDN | 不在本文范围；未来 `akamai/akamai` 与 Cloudflare 并列 |

Compute region 和 Object Storage region 是两个不同字段。例如 VPS 可以使用
`us-east`，Object Storage bucket 使用 `us-east-1`，必须分别记录。

## 2. Bootstrap 顺序

```text
人工创建初始 Linode token
  -> 写入 Vault
  -> 使用 local backend 创建 Object Storage bucket/key
  -> 写入 state 凭据到 Vault
  -> 配置 S3-compatible backend
  -> GitOps 声明 VPS
  -> platform-ops-toolkit 加载 Vault 并执行 plan/apply
```

### 2.1 创建初始 API token

第一次 token 必须由 Akamai Cloud/Linode 管理员在控制台创建。Terraform 不能
使用一个尚不存在的 token 创建自身；`linode_token` 资源只能在已经拥有父级
token 后用于创建受限的子 token。

初始 token 只用于 bootstrap，创建完成后应轮换为权限更窄、生命周期更短的
CI token。不要把 token 写入 GitOps YAML、`terraform.tfvars`、日志或提交内容。

当前 provider tree 的 `templates/provider.tf` 显式读取 `var.linode_token`，
因此 CI 应将 Vault 的 `LINODE_TOKEN` 映射为：

```bash
export TF_VAR_linode_token="${LINODE_TOKEN}"
```

官方 provider 也支持直接读取 `LINODE_TOKEN`，但只有在 provider 不显式覆盖
`token` 时才会直接生效。[Linode provider authentication](https://registry.terraform.io/providers/linode/linode/latest/docs)

### 2.2 创建 Object Storage state bucket

首次创建 state bucket 时不能使用该 bucket 自己作为远端 state。建议使用
`local` backend 执行一个一次性 bootstrap root module，创建：

- 一个启用 versioning 的 Object Storage bucket；
- 一个仅供 Terraform state 使用的 Object Storage access key；
- `prevent_destroy` 保护，避免普通业务 destroy 删除 state bucket。

最小资源形态如下：

```hcl
terraform {
  required_version = ">= 1.5"

  required_providers {
    linode = {
      source  = "linode/linode"
      version = "~> 4.5"
    }
  }
}

provider "linode" {}

variable "object_storage_region" {
  type        = string
  description = "Object Storage region, for example us-east-1"
}

variable "state_bucket" {
  type        = string
  description = "Globally unique Terraform state bucket label"
}

resource "linode_object_storage_key" "terraform_state" {
  label = "terraform-state"
}

resource "linode_object_storage_bucket" "terraform_state" {
  region     = var.object_storage_region
  label      = var.state_bucket
  access_key = linode_object_storage_key.terraform_state.access_key
  secret_key = linode_object_storage_key.terraform_state.secret_key
  versioning = true

  lifecycle {
    prevent_destroy = true
  }
}

output "state_bucket" {
  value = linode_object_storage_bucket.terraform_state.label
}

output "state_endpoint" {
  value = linode_object_storage_bucket.terraform_state.s3_endpoint
}

output "state_access_key" {
  value     = linode_object_storage_key.terraform_state.access_key
  sensitive = true
}

output "state_secret_key" {
  value     = linode_object_storage_key.terraform_state.secret_key
  sensitive = true
}
```

初始化时使用本地 state：

```bash
export LINODE_TOKEN='bootstrap-token'

terraform init
terraform apply \
  -var='object_storage_region=us-east-1' \
  -var='state_bucket=<org>-terraform-state'
```

将 bucket 的 endpoint、bucket 名称、access key 和 secret key 写入 Vault 后，
再通过 `terraform init -migrate-state` 或 `terraform init -reconfigure` 切换
到远端 backend。Object Storage bucket/key 的资源定义见官方文档：
[bucket resource](https://registry.terraform.io/providers/linode/linode/latest/docs/resources/object_storage_bucket)、
[key resource](https://registry.terraform.io/providers/linode/linode/latest/docs/resources/object_storage_key)。

## 3. Vault KV v2 路径

推荐将云账号 token 与 Terraform state 凭据分离：

### 3.1 Akamai Cloud 账号凭据

CLI 语义路径：

```text
kv/CICD/<env>/akamai-cloud/<account_alias>
```

HTTP API 读取路径：

```text
kv/data/CICD/<env>/akamai-cloud/<account_alias>
```

字段：

| 字段 | 是否敏感 | 用途 |
| --- | --- | --- |
| `LINODE_TOKEN` | 是 | Terraform provider API token |

示例：

```bash
vault kv put kv/CICD/uat/akamai-cloud/primary \
  LINODE_TOKEN='...'
```

### 3.2 Terraform state 凭据

沿用平台现有的环境隔离路径：

```text
kv/data/CICD/<env>/iac_state
```

字段：

```text
TF_STATE_ENDPOINT
TF_STATE_BUCKET
TF_STATE_ACCESS_KEY
TF_STATE_SECRET_KEY
TF_STATE_REGION
```

这些字段只用于 S3 backend，不要把它们和 `LINODE_TOKEN` 混成一个账号凭据。

### 3.3 Ansible 登录凭据

如果 VPS 后续交给 Ansible 配置，继续使用现有环境路径：

```text
kv/data/CICD/<env>
```

字段为 `SSH_PRIVATE_DEPLOY_KEY_B64`。私钥不进入 GitOps，也不写入 Terraform
state 之外的派生文件。

## 4. Vault policy

以 UAT、`primary` 账号为例，CI role 至少需要读取：

```hcl
path "kv/data/CICD/uat/akamai-cloud/primary" {
  capabilities = ["read"]
}

path "kv/data/CICD/uat/iac_state" {
  capabilities = ["read"]
}

path "kv/data/CICD/uat" {
  capabilities = ["read"]
}
```

PROD role 只替换为 `prod` 路径。UAT role 不得读取 `prod`，PROD role 不得读取
`uat`。写入、轮换和删除由 Vault 管理员或受保护的 rotation workflow 完成，
日常 Terraform workflow 只读。

## 5. Backend 和 state key

state key 是非机密事实，可以放在 GitOps bootstrap/account declaration 或由
workflow 根据输入拼接；不要把 state key 当作 secret。

推荐格式：

```text
terraform/<env>/<project>/akamai-cloud/<account_alias>/<resource_group>/terraform.tfstate
```

例如：

```text
terraform/uat/svc.plus/akamai-cloud/primary/ai-workspace/terraform.tfstate
```

当前 `akamai-cloud/templates/backend.tf.j2` 负责渲染 S3-compatible backend 的
endpoint/region/workspace prefix；bucket、key 和 backend credentials 应由
`platform-ops-toolkit` 在 `terraform init` 时从 Vault/输入注入，不进入 Git。

## 6. 日常部署

Vault 字段到 Terraform 环境的映射：

```text
kv/data/CICD/uat/akamai-cloud/primary LINODE_TOKEN
  -> TF_VAR_linode_token

kv/data/CICD/uat/iac_state TF_STATE_*
  -> terraform init backend-config
```

部署顺序：

```bash
python3 terraform-hcl-standard/akamai-cloud/scripts/generate.py render \
  --resources <gitops>/resources/<project>/uat/akamai/<group>.yaml \
  --workdir terraform-hcl-standard/akamai-cloud/envs/uat

terraform -chdir=terraform-hcl-standard/akamai-cloud/envs/uat init -reconfigure
terraform -chdir=terraform-hcl-standard/akamai-cloud/envs/uat plan
terraform -chdir=terraform-hcl-standard/akamai-cloud/envs/uat apply

python3 terraform-hcl-standard/akamai-cloud/scripts/generate.py inventory \
  --resources <gitops>/resources/<project>/uat/akamai/<group>.yaml \
  --workdir terraform-hcl-standard/akamai-cloud/envs/uat
```

首次真实部署必须先完成 UAT 验证和 state/backend 检查，再复制到 PROD。本文不
授权任何云端 `apply`；真实账号、bucket、token、state key 和审批由对应环境的
受保护 workflow 提供。

## 7. 检查清单

- [ ] `LINODE_TOKEN` 已写入正确环境和账号路径；没有写入 Git
- [ ] Object Storage bucket 已启用 versioning 和删除保护
- [ ] `TF_STATE_*` 已写入 `kv/data/CICD/<env>/iac_state`
- [ ] state key 包含 provider、project、env、account 和 resource group
- [ ] CI role 只能读取本环境的 Akamai token 和 state 凭据
- [ ] `terraform init` 使用远端 backend，且没有生成本地未追踪 state
- [ ] `terraform plan` 通过审批后才允许 apply
- [ ] apply 后重新生成 `cmdb.json` 和 `inventory.ini`
- [ ] 本期不把 `akamai/akamai` Edge/CDN 资源混入 VPS state
