# Akamai Cloud / Linode VPS Terraform Standard

此目录是 Akamai Cloud（Linode VPS）的 IaC provider tree。结构遵循现有
`aws-cloud`、`gcp-cloud` 和 `vultr-vps` 约定；Terraform 实际使用
`linode/linode` provider，`akamai/akamai` CDN/Edge provider 不属于本目录。

## 边界

- **Terraform provider**：`linode/linode`
- **自动化 provider 路由**：`akamai-cloud`
- **GitOps 声明目录**：`resources/<project>/<env>/akamai/*.yaml`
- **凭据**：`LINODE_TOKEN`，通过 Vault/CI 注入，不进入 YAML、tfvars 或 Git
- **CMDB**：Terraform 只输出运行时事实，Python 将其与 GitOps 静态字段合并
- **删除保护**：`prod` 环境自动选择 protected compute module，渲染
  `lifecycle.prevent_destroy = true`；UAT/test 使用普通 compute module
- **Edge/CDN**：未来使用 `edge_provider: akamai`，与 Cloudflare 并列，不复用
  `cloud_provider`

## 数据流

```text
GitOps resources/<project>/<env>/akamai/*.yaml
  -> scripts/generate.py render
  -> 显式 generated_hosts.tf + provider/backend/tfvars
  -> terraform plan/apply
  -> scripts/generate.py inventory
  -> cmdb.json + inventory.ini
```

环境目录不使用 `for_each`、`count` 或 `dynamic`；多台 VPS 由 Python/Jinja2
渲染成独立的显式 module/resource 块。CMDB 和 Ansible inventory 不直接读取
tfstate。

## 目录

- `modules/compute`：Linode 实例
- `templates/hosts.tf.j2`：每台实例的显式 Linode Firewall 规则
- `modules/storage`：可选块存储卷
- `modules/vpc`：VPC 与 VPC subnet 基础模块
- `templates/`：provider、变量、backend、cloud-init 和渲染模板
- `scripts/generate.py`：`render` / `inventory`
- `scripts/provision.sh`：render → apply → inventory 联动脚本
- `envs/`：Terraform 运行目录，只提交 README 和 `.gitignore`

## GitOps YAML 示例

```yaml
global:
  provider: akamai-cloud
  environment: uat
  region: us-east
  image: linode/debian12
  type: g6-standard-1
  name_prefix: ai-workspace-uat
  user_data_file: cloud-init.yaml

ssh_keys:
  - name: platform-admin
    public: "ssh-ed25519 AAAA... platform-admin"

hosts:
  - name: ai-workspace-node-uat
    type: g6-standard-1
    private_ip: true
    backups_enabled: true
    groups: [ai_workspace, debian]
    tags: [ai-workspace, uat]
    firewall:
      ssh_cidrs: ["10.0.0.0/8"]
      allow_http: false
      allow_https: true
    host_vars:
      role: primary
      service_domains: [ai-workspace.example.com]
```

`ssh_keys` 只允许公钥；API token、state credentials 和私钥必须由运行环境
提供。真实部署接入 GitOps 与 `platform-ops-toolkit` 后，先在 UAT 验证，再按
现有审批链路晋升 PROD。

PROD VPS 的删除保护是 Terraform 侧保护，不是 Linode Cloud Manager 的账号级锁：
`terraform destroy` 会因为 `prevent_destroy` 失败；如需下线，必须由维护者先在受控
变更中切换回普通 compute module 并重新评审。protected module 保持与普通 module
相同的资源地址 `linode_instance.this`，切换 module source 不会主动替换已有 VPS。
该保护不会影响 `terraform plan`、配置更新或 Ansible 部署，也不会为不在该 Terraform
state 中的 existing 主机创建保护。

## 本地校验

```bash
python3 scripts/generate.py render \
  --resources tests/fixtures/linode.yaml \
  --workdir envs/test
terraform -chdir=envs/test fmt -check -recursive
terraform -chdir=envs/test init -backend=false
terraform -chdir=envs/test validate
```

不要对该 fixture 执行 `apply`；它只用于渲染和 Terraform 语法/provider schema
校验。
