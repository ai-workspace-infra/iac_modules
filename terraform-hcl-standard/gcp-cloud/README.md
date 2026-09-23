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

`bootstrap/identity` 已先创建 WIF Pool、Provider 和环境 deploy Service Account；
平台运行目录默认 `create_project = false`，读取已存在的目标项目，并通过运行时
Vault JWT -> Google STS/WIF 注入 `deploy_service_account` 和
`workload_identity_provider`。这样平台 apply 不会再次创建身份资源，也不会要求
使用 Service Account JSON key。

渲染器同时写入 `templates/backend.tf`，统一使用组织 S3-compatible state backend；
endpoint、bucket、key、access key、secret key 和 region 只由 workflow 从 Vault
`CICD` 记录注入。

UAT OIDC 验证可以在 GitOps manifest 的 `spot_vms` 列表声明最小 Compute Engine
Spot VM。该模块复用已创建的 deploy Service Account，不创建新的长期密钥；资源
完成验证后必须执行 Terraform destroy。

## Workload namespace manifests

`kind: GCPWorkloadNamespace` is the parameter-driven contract for independently
managed GCP workload states. The manifest declares the project, account,
region, workspace, state key, network inputs, and resource list; this renderer
turns the declaration into Terraform modules. Each namespace state may declare
`resources.spot_vms`, `resources.cloud_run_services`, or both. Spot VMs require
`name`, `zone`, and `machine_type`; `image` defaults to Debian 12 and
`max_run_duration_seconds` defaults to 3600. Cloud Run entries require `name`
and `image`, and may override `region`.

`spec.enable_cloud_nat` defaults to `true`; set it to `false` for short-lived
validation VMs that do not need outbound internet, avoiding an otherwise
billable Cloud NAT gateway.

The existing `global.cloud_run_service_name` / `cloud_run_image` form remains
supported and keeps the original Terraform address (`module.cloud_run`) for
state compatibility. `spot_vms` at the manifest root also remains supported.
Namespace `state.key` must equal
`terraform/<environment>/<project>/gcp-cloud/<account>/<workspace>/terraform.tfstate`.

Terraform 只负责 GCP 基础资源；Vault secret value、Vault policy 和 Ansible 服务配置
由对应运维链路管理。本目录保留既有 AWS/GCP 示例模块，不在新环境中使用 HCL 循环。
