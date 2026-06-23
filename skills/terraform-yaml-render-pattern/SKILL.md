# Skill: terraform-yaml-render-pattern

## Purpose

约束性规范：在 `iac_modules/terraform-hcl-standard/**` 下编排可批量创建的资源
（典型如多主机 VPS）时，**必须**采用「YAML 描述 → Python+Jinja2 渲染显式 HCL 块
→ Terraform apply → Python 合并生成 CMDB/Inventory」的范式，**不得**在 HCL 内做循环。

这是 binding skill：与本文件冲突的写法一律以本文件为准。
配套约束见 `iac_modules/terraform-hcl-standard/AGENTS.md`。

参考实现（基准，新 env 照此结构落地）：`terraform-hcl-standard/vultr-vps/envs/ai-workspace/`

## Pattern（强制数据流）

```
hosts.yaml (唯一人工入口：资源描述 / CMDB 源)
   │  generate.py render   —— 循环在 Python+Jinja2 侧完成
   ├─▶ generated_hosts.tf            每实例/每 key 一个独立显式 module/resource/data 块
   └─▶ terraform.auto.tfvars.json ──▶ variables.tf   (global 段 -> 变量)
        │
        ▼  terraform apply
   output "cmdb_runtime"  (仅运行时事实：ip / instance_id / 解析后的 os_id)
        │  generate.py inventory  —— 合并 YAML 静态字段 + 运行时输出
        ├─▶ cmdb.json        (IaC ↔ Ansible 契约)
        └─▶ inventory.ini
                 │
                 ▼  Ansible 动态 inventory: playbooks/inventory/terraform_cmdb.py (只读 cmdb.json)
```

## Rules

### MUST NOT
- 不在 env 的 `.tf` 中使用 `for_each` / `count` / `dynamic`。
- 不用 `templatefile()` + `%{ for }` / `%{ if }` 等 HCL 模板控制结构做渲染。

### MUST
- 资源信息由 env 内 `hosts.yaml` 描述；多份资源由 Jinja2 展开为**多个命名唯一的显式块**。
- YAML 全局段经 `terraform.auto.tfvars.json` 传给 `variables.tf`；逐实例字段由 Jinja2 进 `.tf`。
- 机密走环境变量（如 `TF_VAR_vultr_api_key`），**禁止**写入 YAML/tfvars；公钥可入 YAML。
- 共享 `scripts/generate.py`（`--resources`/`--workdir` 参数化）提供 `render` 与
  `inventory` 两个子命令（职责见上图）；不在每个 env 各放一份。
- Terraform 只输出运行时才确定的事实；静态字段（os_name/plan/groups/host_vars…）由 Python 合并。
- 渲染产物（`generated_hosts.tf`、`terraform.auto.tfvars.json`、`cmdb.json`、`inventory.ini`）
  加入 `.gitignore`，不入库。
- `inventory.ini` 中含空格的 host_var 值加引号（`key="a b c"`）。
- Ansible 动态 inventory 只消费 `cmdb.json`，不直接耦合 tfstate；IaC 变更后重跑 `generate.py inventory`。

### SHOULD
- 复用 `modules/compute` 等既有模块，不在 env 内重写 provider 资源。
- 每个用到 provider 的子模块声明 `required_providers`（含正确 `source`）。
- OS 用 `data "vultr_os"` 按 `os_name` 解析 `os_id`，避免硬编码漂移 ID；解析不到时允许直接给 `os_id`。

## Reference Layout（按职责分层）

声明 / 可复用模板 / 组合三层分离，env 目录只保留组合逻辑：

```
<provider>-vps/
  config/resources/<name>-hosts.yaml   # 声明：唯一人工入口 global / ssh_keys / hosts
  templates/                           # 共享：可复用 .tf 与 Jinja2 模板
    provider.tf  variables.tf  cloud-init.yaml   # 共享 .tf/配置（render 时拷入 workdir）
    hosts.tf.j2  inventory.ini.j2                # 渲染模板
  scripts/                             # 共享：组合逻辑（不依赖具体 env）
    generate.py                        # render + inventory；--resources / --workdir 参数化
    provision.sh                       # 一键 render -> apply -> inventory -> (可选) ansible
  modules/<resource>/                  # 复用的资源模块
  envs/<name>/                         # 运行目录（terraform workdir）
    README.md  .gitignore              # 唯二入库文件；其余为渲染产物 + tfstate
  # 渲染产物（落 workdir、不入库）：provider.tf / variables.tf / cloud-init.yaml /
  #   generated_hosts.tf / terraform.auto.tfvars.json / cmdb.json / inventory.ini
```

> 三层共享：**声明**归 `config/resources/`、**可复用 .tf 与模板**归 `templates/`、
> **组合逻辑**归 `scripts/`；env 退化为运行目录。`scripts/generate.py render` 把
> `templates/` 下的 provider/variables/cloud-init 拷入 workdir、渲染出 `generated_hosts.tf`，
> 使 workdir 成为可独立 terraform 的根模块。新增一套主机只加一个 `config/resources/*.yaml`
> + 一个 workdir，复用同一 scripts/templates。

## Operator Checklist（提交前自检）

- `terraform fmt` 无 diff；`terraform validate` 通过。
- `python3 generate.py render` 产出合法 `.tf`（`validate` 通过）。
- 生成的 `inventory.ini` 能被 `ansible-inventory -i <file> --graph` 正确解析。
- 渲染产物已被 `.gitignore` 忽略；机密未入库。
- HCL 内无 `for_each`/`count`/`dynamic`/`templatefile` 控制结构。
