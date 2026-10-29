# Akamai Cloud / Linode VPS Terraform Standard

## Independent production data volumes

`hosts[].volume` creates a separate attached Block Storage device. Production
`prevent_destroy` selection now chooses a protected storage module as well as a
protected compute module. Protection does not survive removing the module from
configuration; the catalog transition and saved-plan gates remain necessary.
`stages.resources.create_only: true` rejects updates/replacements/deletions during
initial creation, while permitting a no-op retry.

IaC never formats or mounts the disk. The declared filesystem is metadata for
Playbooks; it is not a supported `linode_volume` resource argument. Runtime output
and the verified CMDB carry the provider volume ID, attached instance ID, actual
size/region/label and stable `filesystem_path`. Inventory generation refuses a
missing or mismatched disk and invalidates stale derived inventory before publishing.

The `akamai-candidate-hostkey` owner action binds the existing TLS-verified cloud
console fingerprint reader to one checksummed CMDB host. It emits a matching public
known_hosts file for the host owner without executing host commands or printing
provider/console tokens. Consumers must verify the originating IaC receipt first.

此目录是 Akamai Cloud（Linode VPS）的 IaC provider tree。结构遵循现有
`aws-cloud`、`gcp-cloud` 和 `vultr-vps` 约定；Terraform 实际使用
`linode/linode` provider，`akamai/akamai` CDN/Edge provider 不属于本目录。

## 边界

- **Terraform provider**：`linode/linode`
- **自动化 provider 路由**：`akamai-cloud`
- **State identity**: GitOps `iac/catalog.yaml` and its target declarations select namespaces,
  lifecycle and exact state keys. Deployment and preflight share the same loader and
  provider-neutral canonical key generator; there is no provider-local namespace registry.
- **PROD 删除保护**：PROD 声明自动使用 `compute_protected` module，并在
  `linode_instance` 上设置 `lifecycle.prevent_destroy = true`。这是 Terraform
  state 侧的保护；下线必须先通过独立代码变更和审批移除保护。UAT 的临时
  namespace 不使用此 module，`open-platform` 则由 Platform workflow 拒绝 destroy。
- **显式替换授权**：PROD 默认启用删除保护；只有 GitOps YAML 明确写入
  `global.prevent_destroy: false` 且本次 `render` / `provision.sh` 调用显式带上
  `--allow-prod-replacement`，渲染器才会选择未保护的 `compute` module。该参数仅适用
  `akamai-cloud` 的 PROD；provision 回执记录本次是否传入授权。`false` 必须是 YAML
  布尔值，单独修改声明不会解除保护。
- **GitOps 声明目录**：`resources/<project>/<env>/akamai/*.yaml`
- **凭据**：`LINODE_TOKEN`，通过 Vault/CI 注入，不进入 YAML、tfvars 或 Git
- **CMDB**：Terraform 只输出运行时事实，Python 将其与 GitOps 静态字段合并
- **Edge/CDN**：未来使用 `edge_provider: akamai`，与 Cloudflare 并列，不复用
  `cloud_provider`
- **XConnect Zero**：网络 ID、CIDR、Gateway/One 角色和 existing/protected 生命周期
  由 GitOps 声明；Vault 只提供运行时 secret，Ansible 负责节点配置。本 provider tree
  不得为 UAT 的 Ulighthost TW Gateway 或受保护的 Vault Gateway 创建/接管资源。

三网络边界和 Terraform/Ansible/Vault 的职责见
[`../../docs/howto/xconnect-zero-three-network-boundaries.md`](../../docs/howto/xconnect-zero-three-network-boundaries.md)。

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

## Regional entry metadata and ports

GitOps host_vars are preserved in CMDB and the generated INI inventory, including
typed lists and booleans. Use xconnect_region, xconnect_pool, xconnect_fqdn and
xconnect_open_to_users for agent report metadata. firewall.additional_tcp_ports
declares public TCP listeners such as 1443 as explicit inbound rules; each port
must be an integer 1–65535. Declare allow_https: true for the public entry.

Historical UAT targets remain read-only migration entries in the GitOps catalog until
state ownership is verified empty or explicitly handed off. Removing a GitOps active
manifest never grants state deletion or causes automatic retirement.

### Disposable Dev inventory identity

For `environment: dev`, inventory generation requires exactly the declared host
set, a positive runtime Linode `instance_id`, and a usable runtime IPv4 address.
Before reading runtime facts, the Dev inventory phase invalidates only its prior
`cmdb.json` and `inventory.ini` derived artifacts. Missing or unrelated output
then aborts without leaving an earlier address available; state and unrelated
files are untouched. Re-run the
inventory phase after every successful create/replacement so both artifacts use
the latest Terraform `cmdb_runtime`; historical IPs are not connection targets.
A successful offline renderer test does not prove the instance exists or its
host key is trusted. Before a deployment, compare the CMDB instance ID with the
cloud API in the selected account and verify the host key independently.

A Dev physical node may host both isolated feature SIT namespaces and post-merge
UAT namespaces. That stage transition does not change the host resource name,
provider/account, or canonical Dev state key. Creating the host, bootstrapping
K3s/Flux, publishing feature DNS and deploying applications remain separate
owner-controlled actions and require their respective authorization.
