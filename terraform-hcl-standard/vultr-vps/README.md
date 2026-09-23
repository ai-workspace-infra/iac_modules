# Vultr VPS Terraform Standard

此目录提供可复用的 Vultr VPS Terraform 模块、模板和执行脚本。环境及账号资源声明统一由同级 GitOps 仓库维护，路径格式为 `resources/<project>/<env>/vultr/*.yaml`。

## AWS → Vultr 资源映射
- **VPC (aws_vpc)** → `vultr_vpc`：创建私网并自定义 IPv4 段。
- **EC2 (aws_instance)** → `vultr_instance`：创建 VPS/计算实例，支持自定义镜像与云初始化脚本。
- **S3 (aws_s3_bucket)** → `vultr_object_storage`：提供 S3 兼容对象存储，可用于远端状态与应用资产。
- **IAM (aws_iam_user/role + aws_key_pair)** → `vultr_user` + `vultr_ssh_key`：管理子账号权限与 SSH 公钥分发。
- **RDS (aws_db_instance)** → `vultr_database`：托管数据库（MySQL/PostgreSQL/Redis），支持自动备份与高可用套餐。

## 目录结构
- `bootstrap/state/`：初始化 Vultr 对象存储集群与访问密钥，可作为 Terraform 远端状态桶。
- `bootstrap/identity/`：创建子账号与 SSH Key，实现最小权限访问与实例登录。
- `templates/`：包含通用的 `backend.tf` 与 `provider.tf`，用于配置 S3 兼容后端与 Vultr Provider。
- `modules/`：核心模块实现（vpc、compute、storage、iam、data_store），接口与 AWS 模块命名保持一致。
- `envs/`：示例环境（`dev`）展示如何组合模块。

## 使用方式
1. 将 GitOps 仓库 checkout 到本仓库旁，并从 Vault/环境变量注入 provider 和 backend 凭据。资源声明示例位于 `gitops/resources/svc.plus/uat/vultr/ai-workspace.yaml`；其他项目和环境使用对应的 GitOps 路径。
2. 使用引导模板创建状态桶与基础身份：
   ```bash
   terraform -chdir=bootstrap/state init
   terraform -chdir=bootstrap/state apply

   terraform -chdir=bootstrap/identity init
   terraform -chdir=bootstrap/identity apply
   ```
3. 运行时显式传入 GitOps 声明：
   ```bash
   export GITOPS_ROOT="$(cd ../../../gitops && pwd)"
   python3 scripts/generate.py render \
     --resources "$GITOPS_ROOT/resources/svc.plus/uat/vultr/ai-workspace.yaml" \
     --workdir envs/ai-workspace
   terraform -chdir=envs/ai-workspace init
   terraform -chdir=envs/ai-workspace apply
   ```

不要把环境资源声明复制回 `iac_modules` 的 `config/` 目录。
