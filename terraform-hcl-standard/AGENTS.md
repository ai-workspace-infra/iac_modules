# AGENTS.md —— Terraform 模块约束规范（强制）

适用范围：`iac_modules/terraform-hcl-standard/**`。本文件为**约束性规范**，
在本目录下创建/修改 Terraform env 时 **必须遵守**。冲突时以本文件为准。

## 0. 核心范式（MUST）

新建可批量编排的 env（如多主机 VPS）时，**必须**采用如下数据流，
**不得**在 HCL 内做循环：

```
YAML 描述资源
   │  (Python + Jinja2 渲染，循环在此完成)
   ▼
显式 Terraform module/resource 块  ── 每个实例/资源一个独立块，不用 for_each
   │
   ▼
terraform apply
   │
   ▼
Python 合并「YAML 静态信息」+「Terraform 运行时输出」
   │
   ▼
CMDB (cmdb.json) + Ansible inventory (inventory.ini / 动态 inventory)
```

**参考实现（基准，新 env 照此结构落地）：**
`vultr-vps/envs/ai-workspace/`

**配套 binding skill（完整规则与自检清单）：**
`../skills/terraform-yaml-render-pattern/SKILL.md`

## 1. HCL 控制结构禁令（MUST NOT）

- ❌ 禁止在 env 的 `.tf` 中使用 `for_each`、`count`、`dynamic` 块。
- ❌ 禁止用 `templatefile()` + `%{ for }`/`%{ if }` 等 HCL 模板控制结构做渲染。
- ✅ 允许纯函数：`concat`、`merge`、`coalesce`、`jsonencode` 等（非控制结构）。
- ✅ 资源的“多份”由 Python+Jinja2 在生成阶段展开为**多个显式块**，
  每台主机 / 每个 key 对应一个命名唯一的 `module`/`resource`/`data` 块。

> 理由：把循环与条件收敛到 Python/Jinja2 单一处，HCL 保持“扁平、可审计、
> diff 友好”，资源命名稳定，避免 for_each key 漂移导致的重建。

## 2. 资源描述与变量传递（MUST）

- 资源信息**必须**由 env 目录下的 `hosts.yaml`（或等价 `*.yaml`）描述，作为唯一人工入口。
- YAML 的全局段经渲染写入 `terraform.auto.tfvars.json`，**传给 `variables.tf`**；
  逐实例字段由 Jinja2 展开进生成的 `.tf`。
- 机密（API Key、私钥等）**禁止**写入 YAML / tfvars，**必须**走环境变量
  （如 `TF_VAR_vultr_api_key`）。公钥可入 YAML。

## 3. 渲染器约定（MUST）

每个采用本范式的 env **必须**提供 `generate.py`，至少含两个子命令：

- `render`：`hosts.yaml` → `generated_hosts.tf` + `terraform.auto.tfvars.json`
- `inventory`：`terraform output`（运行时事实）+ `hosts.yaml`（静态字段）
  → `cmdb.json` + `inventory.ini`

约定：
- Jinja2 模板放 `templates/*.j2`；标识符经 `tf_id` 过滤器净化为合法 HCL 名。
- Terraform 仅输出 **运行时才确定** 的事实（如 `cmdb_runtime`：ip / instance_id /
  解析后的 os_id）。静态字段（os_name/plan/groups/host_vars 等）由 Python 从 YAML 合并。
- `inventory.ini` 中含空格的 host_var 值**必须**加引号（`key="a b c"`）。
- 渲染产物（`generated_hosts.tf`、`terraform.auto.tfvars.json`、`cmdb.json`、
  `inventory.ini`）为派生物，**必须**加入 `.gitignore`，不入库。

## 4. 模块复用与 OS 解析（SHOULD）

- 实例**应**复用 `modules/compute` 等既有模块，不在 env 内重写 provider 资源。
- 每个使用 provider 的子模块**必须**声明 `required_providers`（含正确 `source`），
  否则 Terraform 误判为 `hashicorp/<name>`。
- OS **应**用 `data "vultr_os"` 按 `os_name` 解析 `os_id`，避免硬编码漂移 ID；
  解析不到时允许在 YAML 直接给 `os_id`。

## 5. IaC ↔ Ansible 联动（MUST）

- CMDB（`cmdb.json`）是 IaC 与 Ansible 的契约。Ansible 侧的动态 inventory
  （`playbooks/inventory/terraform_cmdb.py`）**只**消费 `cmdb.json`，不直接耦合 tfstate。
- IaC 变更后**必须**重跑 `generate.py inventory` 刷新 CMDB/inventory，保持二者一致。

## 6. 提交前自检（MUST）

- `terraform fmt` 无 diff；`terraform validate` 通过。
- `python3 generate.py render` 能产出合法 `.tf`（`validate` 通过）。
- 生成的 `inventory.ini` 能被 `ansible-inventory -i <file> --graph` 正确解析。
- 确认渲染产物已被 `.gitignore` 忽略、机密未入库。
