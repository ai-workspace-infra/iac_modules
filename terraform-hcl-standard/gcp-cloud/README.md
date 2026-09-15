# GCP Cloud Terraform Standard

该目录提供与 `aws-cloud` 模板一一对应的 GCP 版本，用于在 GCP 上快速引导基础设施。结构与 AWS 目录保持一致，包括引导阶段 (bootstrap)、实例示例 (instance) 与模块库 (modules)。

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
1. 在 `templates/backend.tf` 中配置远端状态（GCS 存储桶）。
2. 在 `templates/provider.tf` 中设置 `project`、`region`、`credentials` 等参数。
3. 按需修改 `instance` 下的实例示例，执行：
   ```bash
   terraform -chdir=instance/vpc init
   terraform -chdir=instance/vpc apply
   ```

本目录仅新增 GCP 代码，不改动现有 AWS 模板。

## AI Aggregator UAT Spot

`config/resources/ai-aggregator-vps-uat.yaml` is an optional provider
contract for the personal AI Aggregator UAT. The renderer expands one
Gateway and four CPA nodes into explicit GCP Spot instance modules, then
emits `inventory.ini` and `cmdb.json` from Terraform outputs. The runner must
inject `GCP_PROJECT_ID`, `AI_AGGREGATOR_SSH_PUBLIC_KEY`,
`AI_AGGREGATOR_SSH_CIDR`, and `AI_AGGREGATOR_SOURCE_CIDR`; none of these
runtime values are stored in Git.

The five hosts use `e2-medium` (2 vCPU / 4 GiB) by default so the CPA desktop
and browser can run reliably. The contract is ephemeral and every VM has a
60-minute shutdown guard. OAuth material and service credentials are outside
Terraform and are read from Vault by Ansible.
