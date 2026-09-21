# GCP 新组织对接落地计划

## 目标

将 `xworktech.com` 组织下的 GCP 项目接入现有 AWS Cloud 风格的 IaC、GitOps
和 Ansible 交付链路。UAT 必须先完成验证，生产只允许从已验证的版本晋升。

## 目标项目边界

| 环境 | 项目 ID | 边界 |
| --- | --- | --- |
| UAT | `xwork-open-platform-uat` | 监控、日志、Vault UAT、共享网关和 CI 基础设施 |
| PROD | `xwork-open-platform-prod` | 监控、日志、Vault PROD、共享网关和 CI 基础设施 |
| UAT | `xworktech-ai-workspace-uat` | AI Workspace 测试运行时 |
| PROD | `xworktech-ai-workspace-prod` | AI Workspace 生产运行时 |
| UAT | `xworktech-xconnect-uat` | XConnect 测试运行时 |
| PROD | `xworktech-xconnect-prod` | XConnect 生产运行时 |

所有项目使用同一个 Billing Account，但 IAM、配额、Secret、日志策略和 Cloud
Run 服务完全隔离。Open Platform 是每个环境的一套基础平台，不按产品重复创建。

## Terraform 分层

实施目录为 `terraform-hcl-standard/gcp-cloud`：

1. `bootstrap/state` 创建启用版本化和公共访问防护的 GCS 状态桶。
2. `bootstrap/identity` 创建 GitHub OIDC Workload Identity Pool/Provider，及
   `github-actions-uat`、`github-actions-prod` 两个 Service Account。
3. `modules/project`、`modules/network`、`modules/identity`、`modules/vault_vm`、
   `modules/artifact_registry` 和 `modules/cloud_run` 提供项目/API、网络、身份、
   Vault VM、镜像仓库和运行时基础资源。
4. GitOps 仓库 `resources/xworktech.com/<env>/gcp/open-platform-*.yaml` 是资源唯一人工入口；共享
   `scripts/generate.py` 将清单展开为 `envs/uat`、`envs/prod` 的显式
   module/resource 块。

环境目录不得使用 `for_each`、`count` 或 `dynamic`。机密不进入 YAML、tfvars 或
Git，使用运行环境变量、Vault 或 GitHub Environment secrets。

## 身份和权限

GitHub Actions 使用短期 OIDC 凭据：

```text
GitHub OIDC
  -> Workload Identity Provider
  -> github-actions-uat / github-actions-prod
  -> 对应环境项目
```

Provider 条件必须限制到 `ai-workspace-infra/platform-ops-toolkit`，并按 GitHub
Environment 分开 service account。不得创建长期 JSON 私钥。

OIDC 只负责 CI 到 GCP 的身份交换；应用间 JWT 由 API Gateway/服务签发和验证，
JWT signing key 由 Vault 管理，不能写入 GitHub Variables 或镜像。

KV v2 的环境路径、字段契约和 policy 边界见
[`vault-kv-paths.md`](vault-kv-paths.md)。

## Terraform 与 Ansible 分工

| 系统 | 管理内容 |
| --- | --- |
| Terraform | 组织项目、API、VPC、IAM、Service Account、WIF、VM、Artifact Registry、Cloud Run 基础资源 |
| Ansible | Vault 集群、监控套件、Gitea、CI Runner、主机加固和服务配置 |
| GitOps | 环境拓扑、域名、镜像 tag、Cloud Run 参数和发布期望状态 |

同一资源只能有一个事实来源。Terraform 输出的运行时事实写入 CMDB，Ansible
动态 inventory 只消费 CMDB，不读取 tfstate。

## Vault 与基础平台

- UAT 使用独立 Vault 实例或小型 Raft 集群。
- PROD 使用至少 3 个跨可用区 Compute Engine 节点。
- Vault 节点仅使用私有 IP，通过 IAP、VPN 或跳板机管理。
- 使用 Cloud KMS 保护自动解封密钥，快照加密后写入 Cloud Storage。
- VPS 继续承载自建监控套件、Gitea 和 CI Runner；数据和凭据不与 PROD Vault 混放。

## 实施阶段

### 阶段 0：基线修复

- 修复 GCP 示例目录中现有 HCL 语法错误。
- 为每个子模块补齐 `required_providers`。
- 统一 provider、backend 和变量命名。

验收：

```bash
terraform fmt -check -recursive
terraform validate
```

### 阶段 1：状态和身份

- 创建 Open Platform 状态桶。
- 应用 `bootstrap/identity`。
- 将 WIF provider、UAT/PROD service account 输出写入 GitHub Environments。

验收：GitHub Actions 能通过 OIDC 执行 `gcloud projects describe`，且 UAT 身份
无法访问 PROD 项目。

### 阶段 2：UAT 平台

- 创建 UAT VPC、Artifact Registry、Cloud Run 基础设施。
- 使用 Ansible 部署监控、Vault UAT 和 Gitea Runner 对接。
- 在 `gitops/topology/uat` 写入平台项目声明。

验收：UAT OIDC smoke test、Terraform plan/apply、Ansible syntax-check、服务
健康检查全部通过。

### 阶段 3：PROD 平台

- 从 UAT 已验证的 module 版本晋升，不直接复制运行时状态。
- 创建 PROD 私有网络和 Vault 多节点集群。
- 将 PROD workflow 限制为受保护 tag/分支，并要求环境审批。

验收：PROD plan 与 UAT 只有环境变量差异；未通过 UAT 门禁时 PROD workflow 不可运行。

## 发布门禁与回滚

发布顺序固定为：

```text
state -> identity -> UAT plan/apply -> UAT smoke test -> PROD approval -> PROD apply
```

每次发布保存 Terraform plan、OIDC smoke test、Ansible check 和运行时健康检查结果。
回滚优先恢复 GitOps 版本和 Cloud Run revision；Vault 使用最近一次加密快照恢复。
不得通过删除 Billing Account、项目或状态桶来回滚。

## 完成标准

- UAT/PROD 项目均挂在 `xworktech.com` 组织下。
- GitHub Actions 不再使用长期 GCP 私钥。
- UAT 与 PROD Service Account、Vault、Secret、日志和域名完全隔离。
- Terraform、Ansible、GitOps 三方的环境名称和项目 ID 一致。
- `terraform fmt`、`terraform validate`、Ansible syntax-check 和 OIDC smoke test 全部通过。
