# ai-workspace env —— YAML 描述资源 + Python/Jinja2 渲染 + Ansible 动态 inventory

在 `vultr-vps` 模块基础上，做到 **IaC 创建主机 ↔ Ansible inventory** 的联动，且满足约束：

- **不使用 HCL 控制结构**（无 `for_each`/`count`/`dynamic`/`templatefile` 循环）。
- **用 Python + Jinja2 渲染 YAML** 生成显式的 Terraform `module`/`resource`/`data` 块。
- `hosts.yaml` 描述资源信息，全局段经 `terraform.auto.tfvars.json` 传给 `variables.tf`。

默认创建两台机器（均 **4 核 8G / 公网 IP / 不开备份**）：`ai-debian13`(Debian 13)、`ai-ubuntu2604`(Ubuntu 26.04)。

## 数据流

```
hosts.yaml ──generate.py render──▶ generated_hosts.tf      (逐主机显式 module 块，无 for_each)
   │                              └ terraform.auto.tfvars.json ──▶ variables.tf
   │
   └──────────────▶ terraform apply ──▶ output cmdb_runtime (ip/instance_id/os_id)
                                              │
hosts.yaml(静态字段) + cmdb_runtime ──generate.py inventory──▶ cmdb.json + inventory.ini
                                              │
                                  playbooks/inventory/terraform_cmdb.py (Ansible 动态 inventory 读 cmdb.json)
```

> 循环逻辑全部在 Python/Jinja2 侧：每台主机 / 每个 SSH key 都被展开成
> `generated_hosts.tf` 里独立的显式块，HCL 内不出现任何控制结构。

## 文件

| 文件 | 角色 |
|------|------|
| `hosts.yaml` | **唯一人工入口**：global / ssh_keys / hosts 资源描述 (CMDB 源) |
| `generate.py` | `render`：YAML→tf+tfvars；`inventory`：tf 输出+YAML→cmdb.json+inventory.ini |
| `templates/hosts.tf.j2` | 渲染逐主机 module/data 块与 `vultr_ssh_key` 资源 |
| `templates/inventory.ini.j2` | 渲染静态 inventory.ini |
| `variables.tf` | 全局变量声明（值来自 tfvars.json） |
| `provider.tf` / `cloud-init.yaml` | Provider 与云初始化 |
| `provision.sh` | 一键：render → apply → inventory →（可选）跑 Ansible |
| `../../../../../playbooks/inventory/terraform_cmdb.py` | Ansible 动态 inventory 脚本 |

> `generated_hosts.tf` / `terraform.auto.tfvars.json` / `cmdb.json` / `inventory.ini`
> 均为渲染产物，已在 `.gitignore` 中忽略。

## 用法

```bash
export TF_VAR_vultr_api_key=xxxxxxxx
# 编辑 hosts.yaml（填入真实 ssh 公钥 / 调整主机），然后：
./provision.sh                              # 渲染 + 创建 + 生成 inventory

# 用动态 inventory 驱动 Ansible
cd ../../../../../playbooks
ansible ai_workspace -i inventory/terraform_cmdb.py -m ping
ansible-playbook -i inventory/terraform_cmdb.py setup-ai-workspace-all-in-one.yml
```

分步执行：

```bash
python3 generate.py render        # YAML -> generated_hosts.tf + terraform.auto.tfvars.json
terraform init && terraform apply # 建机
python3 generate.py inventory     # -> cmdb.json + inventory.ini
```

## 调整主机

改 `hosts.yaml` 即可增删机器或改套餐/区域/分组/host_vars，重跑 `generate.py render`。
`groups` 决定主机进入哪些 Ansible 组；`host_vars` 会进入 inventory 行与动态 inventory 的 `hostvars`。

> OS 通过 `os_name` 自动解析 `os_id`（避免硬编码漂移的镜像 ID）。名称查不到时用
> `vultr-cli os list` 核对，或在该主机直接写 `os_id`。
