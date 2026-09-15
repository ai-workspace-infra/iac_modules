[🇺🇸 English](README.md) | [🇨🇳 中文](README.zh.md)

# AI Workspace 基础设施模块仓库 (`iac_modules`)

`iac_modules` 是 AI Workspace 平台的基础设施即代码（IaC）仓库。它从同级 GitOps 仓库读取 YAML 声明，
由 Python + Jinja2 渲染成显式的 Terraform HCL，按环境 apply，并产出供 Ansible 消费的 CMDB（`cmdb.json`）。
本仓库中的 Terraform 只负责计算 / 网络 / 存储 / 身份等云资源，软件层配置属于 CMDB 契约另一侧的
playbooks 仓库。

## 核心范式

```
../gitops/resources/<project>/<env>/<provider>/<group>.yaml          声明层 —— 唯一的人工维护入口
        │   scripts/generate.py render       循环在 Python + Jinja2 侧完成，绝不进 HCL
        ▼
generated_hosts.tf                           每台主机一个命名唯一的显式 module/resource 块
terraform.auto.tfvars.json ──▶ variables.tf  YAML 的 global 段
        │   terraform apply
        ▼
output "cmdb_runtime"                        仅运行时才确定的事实（ip / instance_id / 解析后的 os_id）
        │   scripts/generate.py inventory    合并 YAML 静态字段 + Terraform 运行时输出
        ▼
cmdb.json + inventory.ini                    IaC ↔ Ansible 契约
```

由此派生的强制约束，完整条款见
[`terraform-hcl-standard/AGENTS.md`](terraform-hcl-standard/AGENTS.md) 与 [`skills/`](skills)：

- **HCL 内禁用控制结构**：不得使用 `for_each` / `count` / `dynamic`，不得用 `templatefile()` 配合
  `%{ for }` / `%{ if }` 渲染；「多份资源」在渲染阶段展开为多个命名唯一的显式块。
- **拓扑不进 HCL**：区域、机型、实例数量、域名与 host_vars 一律写在 YAML 里。
- **HCL 内禁止内嵌脚本**：不得使用 `local-exec` provisioner，不得用 `null_resource` 跑 shell/python。
- **状态按环境隔离**：`sit` / `uat` / `prod` 绝不复用同一个 backend key。
- **机密不落文件**：API Key 通过 `TF_VAR_*` 环境变量注入；IaC 生成的凭证直接推送 Vault 供 Ansible
  读取，绝不写入 YAML / tfvars，也不以文件形式向后传递。
- **渲染产物不入库**：`generated_hosts.tf`、`terraform.auto.tfvars.json`、`cmdb.json`、
  `inventory.ini` 均被 gitignore；运行目录只跟踪 `README.md` 与 `.gitignore`。

## 单个 Provider 内的分层

`terraform-hcl-standard/` 下每个 provider 都遵循同一套三层切分 —— 声明 / 可复用模板 / 组合逻辑，
env 目录退化为纯粹的 Terraform 运行目录。

| 分层 | 路径 | 职责 | 是否入库 |
|------|------|------|----------|
| 声明 | `gitops/resources/<project>/<env>/<provider>/*.yaml` | 按环境、按资源分类描述拓扑 | ✅ |
| 声明 | 同级 `gitops/resources/<project>/<env>/<provider>/` | 资源拓扑及账号/bootstrap 事实 | 外部 GitOps 仓库 |
| 模板 | `<provider>/templates/` | 共享的 `provider.tf`、`variables.tf`、`backend.tf`、`cloud-init.yaml` 及对应 `.j2` | ✅ |
| 组合 | `<provider>/scripts/generate.py`、`provision.sh` | `render` + `inventory` 子命令与一键编排 | ✅ |
| 模块 | `<provider>/modules/<resource>/` | 被渲染块复用的资源模块 | ✅ |
| 根模块 | `<provider>/component/`（AWS）、`<provider>/instance/`（GCP） | 逐资源的 Terraform 根模块，各带一个 `Makefile` | ✅ |
| 运行目录 | `<provider>/envs/<name>/` | Terraform workdir，承接渲染产物与 tfstate | 仅 README + `.gitignore` |
| Bootstrap | `<provider>/bootstrap/{state,lock,identity}` | 远端状态桶、锁表、部署角色/用户，先于一切执行 | ✅ |

## Provider 与成熟度分类

| Provider | 路径 | 状态 | 模块数 | 现状 |
|----------|------|------|--------|------|
| AWS | `terraform-hcl-standard/aws-cloud/` | 生产可用 | 14 | Terragrunt bootstrap（`state` / `lock` / `identity`）、`component/` 根模块、`sit` + `uat` + `prod` 资源声明、render + inventory 脚本 |
| Vultr | `terraform-hcl-standard/vultr-vps/` | 生产可用 —— 渲染范式的基准实现 | 7 | 四个运行目录（`ai-workspace`、`dev`、`platform-ops-toolkit`、`site-migration-toolkit`）、`sit` + `uat` + `prod` 声明、`provision.sh` |
| 阿里云 | `terraform-hcl-standard/ali-cloud/` | 部分完成 | 9 | 模块 + bootstrap + `envs/dev`；声明位于外部 GitOps |
| GCP | `terraform-hcl-standard/gcp-cloud/` | 核心基线 | 14 | 项目/API、VPC、IAM/WIF、Vault VM、Artifact Registry 与 Cloud Run 模块 |
| Azure | `terraform-hcl-standard/azure-cloud/` | 骨架 | 14 | 每个模块仅一个 `main.tf`；无运行目录、无资源声明 |

`terraform-hcl-standard/utils/` 存放共享的 Python 渲染器（`renderer.py`、`config_loader.py`、
`render_provider_backend.py`）。

## 模块目录（按能力域分类）

| 能力域 | AWS | 阿里云 | Vultr | GCP / Azure（骨架） |
|--------|-----|--------|-------|---------------------|
| 身份与治理 | `iam`、`landingzone` | `ram` | `iam` | `iam`、`landingzone` |
| 计算 | `ec2`、`keypair`、`ami_lookup` | `ecs` | `compute`、`resize-instance` | `ec2`、`keypair`、`ami_lookup` |
| 网络 | `vpc`、`sg`、`alb`、`nlb` | `vpc`、`alb`、`nlb` | `vpc` | `vpc`、`sg`、`alb`、`nlb` |
| 数据与存储 | `rds`、`redis`、`msk`、`s3` | `rds`、`redis`、`oss` | `data_store`、`storage` | `rds`、`redis`、`msk`、`s3` |
| 拆除 | `bootstrap-destroy` | `bootstrap-destroy` | `bootstrap-destroy` | `bootstrap-destroy` |

> GCP 与 Azure 目录里声明的确实是 `google_*` / `azurerm_*` 资源，但目录名沿用了 AWS 的叫法
> （`ec2`、`s3`、`msk`、`ami_lookup`），命名尚未归一化。

## 环境与资源分类

三套环境，各自拥有独立的 YAML 目录、独立的运行目录与独立的状态：
**`sit`**（集成）、**`uat`**（预生产）、**`prod`**（生产）。

资源分类（resource group）是环境内的声明单位 —— 一个分类一份 YAML，一个分类一次 Terraform 运行：

| 分类 | Ansible group / tags | 承载内容 |
|------|----------------------|----------|
| `web-saas` | `web_saas`、`database` | Console / accounts / PostgreSQL SaaS 主机，含 Caddy 需要签发证书的对外服务域名 |
| `ai-workspace` | `ai_workspace`、`database` | AI workspace 应用节点 |
| `infra-platform` | `infra_platform`、`database` | 平台侧共享服务 |
| `agent-proxy` | `agent_proxy` | Agent 出口 / 代理节点 |
| `action-runner` | `action_runner` | 自托管 CI Runner |
| `all-in-one`（仅 `sit`） | 混合 | 整套栈收敛到单台 SIT 主机 |

`uat` 与 `prod` 刻意是独立的声明与独立的状态：某次 apply 产出的 CMDB 就是该环境的部署事实来源，
任何一次运行都不得指向另一个环境的主机变量。

## Terraform 之外的组成部分

| 路径 | 内容 |
|------|------|
| `vpn-overlay/` | 跨站点 L2/L3 覆盖网络：`wireguard/`、`xray/`、`vxlan/`、`gretap/`、`config/sites.yaml` 与拓扑图 |
| `skills/` | 约束性规范 —— `IAC-Spec`（IaC 红线）、`terraform-yaml-render-pattern`（渲染范式）、`release-branch-policy` |
| `scripts/` | 仓库级辅助脚本 —— `dynamic_inventory.py`、WireGuard 密钥生成、gitleaks 自动修复，以及 `workflows/` 下的 Flux / Ansible / kubeconfig / xconfig helper |
| `.github/actions/` | 流水线定义 —— 各云的 Landing Zone 基线、基础设施资源、监控 exporter/server、SSL 证书续期 |
| `.github/workflows/` | `validate-release-pr.yml` —— 本仓库唯一实际运行的 workflow |
| `example/` | 参考样例：Pulumi（Python）与 AWS / Azure / GCP 的原生 Terraform |
| `docs/` | 双语文档集，入口见 [`docs/README.md`](docs/README.md) |

## 快速开始

> 这些模块面向流水线与 `generate.py` 驱动；直接进入某个 provider 目录手跑 `terraform` 是无效的 ——
> 运行目录要在 render 之后才成为可用的根模块。

### 前置依赖

- Terraform >= 1.5.0
- Terragrunt >= 0.67.14（仅 AWS bootstrap 需要）
- Python 3，安装 `PyYAML` 与 `Jinja2`（`requirements.txt` 除此之外还包含 Pulumi 示例的依赖）
- Provider 凭证 —— AWS 走标准凭证链 / OIDC，Vultr 走 `TF_VAR_vultr_api_key`

### 1. 账号 Bootstrap（一次性）

账号事实（桶名、锁表、角色名）来自外部 GitOps 仓库，而非本仓库：

```bash
git clone https://github.com/ai-workspace-infra/gitops.git ../gitops
cd terraform-hcl-standard/aws-cloud/bootstrap
BOOTSTRAP_CONFIG_PATH=../../../../gitops/resources/<project>/<env>/<provider>/bootstrap.yaml make bootstrap-init bootstrap-apply
```

创建 S3 状态桶（开启版本控制与加密）、DynamoDB 锁表与部署角色/用户。凭证模式与拆除流程见
[`aws-cloud/README.md`](terraform-hcl-standard/aws-cloud/README.md)。

### 2. 渲染、apply 并产出 CMDB

```bash
export TF_VAR_vultr_api_key=...
cd terraform-hcl-standard/vultr-vps/scripts

RESOURCES=../../../../gitops/resources/<project>/uat/<provider>/web-saas.yaml \
WORKDIR=../envs/ai-workspace \
./provision.sh
```

`provision.sh` 按序执行四步 —— `generate.py render` → `terraform init && apply` →
`generate.py inventory` →（可选）Ansible。也可以逐步执行：

```bash
python3 generate.py render    --resources ../../../../gitops/resources/<project>/uat/<provider>/web-saas.yaml --workdir ../envs/ai-workspace
terraform -chdir=../envs/ai-workspace init && terraform -chdir=../envs/ai-workspace apply
python3 generate.py inventory --resources ../../../../gitops/resources/<project>/uat/<provider>/web-saas.yaml --workdir ../envs/ai-workspace
```

### 3. 交接给 Ansible

playbooks 仓库通过动态 inventory（`playbooks/inventory/terraform_cmdb.py`）消费 `cmdb.json`，
不直接读取 tfstate。每次基础设施变更后都要重跑 `generate.py inventory`。

```bash
ansible web_saas -i ../../../../playbooks/inventory/terraform_cmdb.py -m ping
```

## 动手改之前先读

- [`terraform-hcl-standard/AGENTS.md`](terraform-hcl-standard/AGENTS.md) —— Terraform 强制约束
- [`skills/IAC-Spec/SKILL.md`](skills/IAC-Spec/SKILL.md) —— IaC 红线与 IaC ↔ Config-as-Code 边界
- [`skills/terraform-yaml-render-pattern/SKILL.md`](skills/terraform-yaml-render-pattern/SKILL.md) —— 渲染范式与提交前自检清单
- [`skills/release-branch-policy/SKILL.md`](skills/release-branch-policy/SKILL.md) —— 分支与发布策略

提交前自检：`terraform fmt` 无 diff、`terraform validate` 通过、`generate.py render` 产出合法 HCL、
`ansible-inventory --graph` 能解析生成的 inventory、渲染产物与机密未被 stage。

## 已知缺口

- Azure 仍是骨架；GCP 核心基线已可通过 GitOps 声明渲染和校验。
- 阿里云保留模块与 `envs/dev` 工作目录，后续声明统一放入 GitOps。
- 各渲染器默认读取同级 GitOps；切换项目、环境或云厂商时显式传入 `--resources` / `RESOURCES`。
- 文档归并进度记录在 [`docs/DOC_COVERAGE.md`](docs/DOC_COVERAGE.md)。

## 文档 / 链接

- [官方网站](https://www.svc.plus/)
- [ai-workspace-infra 组织](https://github.com/ai-workspace-infra)
