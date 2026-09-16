# GCP Cloud Terraform Standard

落地顺序、项目边界、OIDC/JWT 与 UAT→PROD 门禁见
[`docs/gcp-landing-plan.md`](docs/gcp-landing-plan.md)。

当前已落地 Terraform 核心模块：`project`（项目/API）、`network`（VPC/NAT）、
`identity`（Service Account/WIF/IAM）、`vault_vm`（私有 Vault VM）、
`artifact_registry` 和 `cloud_run`。UAT/PROD 由
GitOps 仓库 `resources/xworktech.com/<env>/gcp/open-platform-*.yaml` 声明，使用
`scripts/generate.py` 渲染为
显式 Terraform 块；Vault KV v2 路径契约见
[`docs/vault-kv-paths.md`](docs/vault-kv-paths.md)。

该目录提供与 `aws-cloud` 模板一一对应的 GCP 版本，用于在 GCP 上快速引导基础设施。结构与 AWS 目录保持一致，包括引导阶段 (bootstrap)、实例示例 (instance) 与模块库 (modules)。运行 root 使用组织统一的 S3-compatible state backend，而不是 GCS backend；key 与 Vault 契约见 [`../../docs/howto/unified-iac-state-contract.md`](../../docs/howto/unified-iac-state-contract.md)。

## 模板映射
- **bootstrap/identity → IAM**：创建基础服务账号与自定义角色，替代 AWS IAM 角色与策略。
- **bootstrap/state → Cloud Storage**：创建启用版本化和 generation-based locking 的 GCS 存储桶，对应 AWS S3 + DynamoDB 锁表。
- **modules**：保留原始模块命名（alb、nlb、vpc 等），内部实现改为 GCP 资源：
  - `alb`/`nlb`：使用 Google HTTP(S) / TCP 负载均衡。
  - `ec2`：映射到 Compute Engine 实例或 MIG。
  - `keypair`：生成 SSH 密钥并写入元数据。
  - `msk`：映射到 Pub/Sub（发布/订阅）。
  - `rds`：映射到 Cloud SQL。
  - `s3`：映射到 Cloud Storage。
  - `vpc`：使用 VPC 网络与子网。
  - `ami_lookup`：映射到最新公共镜像查找（debian/ubuntu）。
  - `iam`：分配 IAM 角色与绑定。
  - `landingzone`：创建基础网络、日志与审计配置。
  - `redis`：映射到 Memorystore。
  - `sg`：映射到 VPC 防火墙规则。

## 使用方式
1. 先在 GitOps 的 `resources/xworktech.com/<env>/gcp/` 修改环境资源清单，不把机密写入 YAML。
2. 设置 `TF_VAR_billing_account_id`，渲染目标环境：
   ```bash
   python3 scripts/generate.py render \
     --resources ../../../gitops/resources/xworktech.com/uat/gcp/open-platform-uat.yaml \
     --workdir envs/uat
   terraform -chdir=envs/uat init
   terraform -chdir=envs/uat plan
   ```
3. UAT 通过验证并获得发布审批后，再对 `open-platform-prod.yaml` 重复渲染和计划。

Terraform 只负责 GCP 基础资源；Vault secret value、Vault policy 和 Ansible 服务配置
由对应运维链路管理。本目录保留既有 AWS/GCP 示例模块，不在新环境中使用 HCL 循环。
