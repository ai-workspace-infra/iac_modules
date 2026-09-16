# Azure Cloud Terraform Standard

该目录提供与 `aws-cloud` 模板一一对应的 Azure 版本，延续相同的目录与模块命名（bootstrap、config、modules、envs），便于将 AWS 使用习惯映射到 Azure。

## 模板映射（AWS → Azure）
- **bootstrap/state → Storage Account**：创建存储账户与容器用于 Terraform 远端状态。
- **bootstrap/lock → Cosmos DB Table API**：提供无服务器键值表存储。
- **bootstrap/identity → RBAC 角色分配**：为指定主体分配内置角色，替代 AWS IAM 角色/策略。
- **modules**：保留 AWS 模块命名，内部实现替换为 Azure 服务：
  - `vpc`：虚拟网络 + 子网（Virtual Network/Subnet）。
  - `alb`：应用程序网关（Application Gateway）。
  - `nlb`：标准负载均衡器（Standard Load Balancer）。
  - `ec2`：Linux 虚拟机（Virtual Machine）。
  - `s3`：存储账户与容器（Storage Account + Container）。
  - `rds`：PostgreSQL 灵活服务器（Flexible Server）。
  - `redis`：Azure Cache for Redis。
  - `sg`：网络安全组与规则（Network Security Group）。
  - `iam`：基于内置角色的角色分配（Role Assignment）。
  - `ami_lookup`：公共镜像查找（Ubuntu 平台镜像）。
  - `landingzone`：基础资源组与日志工作区。
  - `keypair`：生成 SSH 密钥对。
  - `msk`：事件中心命名空间与 Hub（Event Hubs）。

## 使用方式
1. 运行时从 Vault `CICD/<env>/iac_state` 注入组织统一 S3-compatible backend；不要在 `templates/backend.tf` 配置 Azure 存储账户或 state 凭据。key 规则见 [`../../docs/howto/unified-iac-state-contract.md`](../../docs/howto/unified-iac-state-contract.md)。
2. 在 `templates/provider.tf` 中设置 `subscription_id`、`tenant_id`、`location` 等参数。
3. 参考 `envs/dev/main.tf`，按需修改变量后执行：
   ```bash
   terraform -chdir=envs/dev init
   terraform -chdir=envs/dev apply
   ```

本目录新增 Azure 代码，不改动现有 AWS 模板。
