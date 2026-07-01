# ai-workspace env —— YAML 描述资源 + Python/Jinja2 渲染 + Ansible 动态 inventory

在 `vultr-vps` 模块基础上，做到 **IaC 创建主机 ↔ Ansible inventory** 的联动，且满足约束：

- **不使用 HCL 控制结构**（无 `for_each`/`count`/`dynamic`/`templatefile` 循环）。
- **用 Python + Jinja2 渲染 YAML** 生成显式的 Terraform `module`/`resource`/`data` 块。
- 资源声明放共享 `config/resources/ai-workspace-hosts.yaml`，全局段经 `terraform.auto.tfvars.json` 传给 `variables.tf`。

默认创建两台机器（均 **4 核 8G / 公网 IP / 不开备份**）：`ai-debian13`(Debian 13)、`ai-ubuntu2604`(Ubuntu 26.04)。

## 目录分层（声明 / 共享模板 / 共享脚本 / 运行目录）

```
vultr-vps/
  config/resources/ai-workspace-hosts.yaml   # 声明：唯一人工入口 / CMDB 源
  templates/                                 # 共享：provider/变量/云初始化/渲染模板
    provider.tf  variables.tf  cloud-init.yaml  hosts.tf.j2  inventory.ini.j2
  scripts/                                   # 共享：组合逻辑（可被多套声明复用）
    generate.py  provision.sh
  modules/{compute,iam,...}                  # 复用的资源模块
  envs/ai-workspace/                         # 运行目录（terraform workdir）：仅 README/.gitignore
                                             #   其余文件为渲染产物 + tfstate，均 gitignore
```

> 本 env 已退化为"运行目录"：组合逻辑提到共享 `scripts/`，可复用的 .tf 与模板提到
> 共享 `templates/`。新增一套主机只需加一个 `config/resources/<name>-hosts.yaml`
> 和一个 workdir，复用同一套 scripts/templates。

## 数据流

```
config/resources/ai-workspace-hosts.yaml
   │  scripts/generate.py render --resources <yaml> --workdir <env>
   │     （读 templates/hosts.tf.j2；拷 templates/{provider,variables,cloud-init} 入 workdir）
   ├─▶ workdir/generated_hosts.tf   (逐主机显式 module 块，无 for_each)
   ├─▶ workdir/{provider.tf, variables.tf, cloud-init.yaml}   (拷自 templates/)
   └─▶ workdir/terraform.auto.tfvars.json ──▶ variables.tf
        │
        └─▶ terraform -chdir=workdir apply ──▶ output cmdb_runtime (ip/instance_id/os_id)
                                        │
YAML(静态字段) + cmdb_runtime ──scripts/generate.py inventory──▶ workdir/{cmdb.json, inventory.ini}
                                        │
                            playbooks/inventory/terraform_cmdb.py (Ansible 动态 inventory 读 cmdb.json)
```

> 循环逻辑全部在 Python/Jinja2 侧：每台主机 / 每个 SSH key 都被展开成
> `generated_hosts.tf` 里独立的显式块，HCL 内不出现任何控制结构。

## 文件

| 文件 | 角色 |
|------|------|
| `../../config/resources/ai-workspace-hosts.yaml` | **唯一人工入口**：global / ssh_keys / hosts 资源声明 (CMDB 源) |
| `../../templates/{hosts.tf.j2, inventory.ini.j2}` | Jinja2 渲染模板（主机 module/data 块、静态 inventory） |
| `../../templates/{provider.tf, variables.tf, cloud-init.yaml}` | 共享 .tf/配置，render 时拷入运行目录 |
| `../../scripts/generate.py` | `render`：YAML+模板→workdir 产物；`inventory`：tf 输出+YAML→cmdb.json+inventory.ini |
| `../../scripts/provision.sh` | 一键：render → apply → inventory →（可选）跑 Ansible |
| `../../../../../playbooks/inventory/terraform_cmdb.py` | Ansible 动态 inventory 脚本 |
| 本目录 `.gitignore` / `README.md` | 运行目录里唯二入库的文件 |

> 运行目录里的 `generated_hosts.tf` / `provider.tf` / `variables.tf` / `cloud-init.yaml` /
> `terraform.auto.tfvars.json` / `cmdb.json` / `inventory.ini` 均为渲染产物，已 `.gitignore` 忽略。

## 用法

```bash
export TF_VAR_vultr_api_key=xxxxxxxx
# 编辑 config/resources/ai-workspace-hosts.yaml（填真实 ssh 公钥 / 调整主机），然后：
../../scripts/provision.sh                  # 渲染 + 创建 + 生成 inventory

# 用动态 inventory 驱动 Ansible
cd ../../../../../playbooks
ansible ai_workspace -i inventory/terraform_cmdb.py -m ping
ansible-playbook -i inventory/terraform_cmdb.py setup-ai-workspace-all-in-one.yml
```

分步执行（在 vultr-vps 根目录）：

```bash
python3 scripts/generate.py render      # -> envs/ai-workspace/ 渲染产物
terraform -chdir=envs/ai-workspace init && terraform -chdir=envs/ai-workspace apply
python3 scripts/generate.py inventory   # -> cmdb.json + inventory.ini
```

> 多套主机：加 `config/resources/<name>-hosts.yaml` + 一个 workdir，复用同一 scripts：
> `scripts/generate.py render --resources config/resources/<name>-hosts.yaml --workdir envs/<name>`

## 调整主机

改 `../../config/resources/ai-workspace-hosts.yaml` 即可增删机器或改套餐/区域/分组/host_vars，重跑 `scripts/generate.py render`。
`groups` 决定主机进入哪些 Ansible 组；`host_vars` 会进入 inventory 行与动态 inventory 的 `hostvars`。

> OS 通过 `os_name` 自动解析 `os_id`（避免硬编码漂移的镜像 ID）。名称查不到时用
> `vultr-cli os list` 核对，或在该主机直接写 `os_id`。
