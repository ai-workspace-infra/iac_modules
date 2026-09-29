# XConnect Zero 三网络边界契约

本文是 `iac_modules` 的边界说明。它不创建网络、不保存凭据，也不替代
GitOps 的资源声明。三张 XConnect Zero 网络的实际 ID、CIDR、区域、Gateway
引用和生命周期必须以 GitOps 为唯一的非敏感事实源。

## 三张网络

| 网络 | 用途 | Gateway | 管理方式 | IaC 约束 |
|---|---|---|---|---|
| `net_security_vault` | 安全管理网络 | 受保护的 `vault-prod-0` | existing-protected | 只引用，不 import、改名、更新或 destroy |
| `net_uat` | UAT 跨区域零信任网络 | Ulighthost existing 的 TW 节点 | existing + Ansible | 不创建 Terraform VM；由 playbook 配置 Gateway/One |
| `net_prod_dedicated` | PROD 独立生产网络 | 独立的 PROD Gateway 节点 | Terraform + Ansible | 只有 GitOps 声明并完成 provider/account 审批后才能 apply |

当前规划的非敏感网络事实为：

```text
net_security_vault   -> 10.79.0.0/24 -> vault-prod-0
net_uat              -> 10.77.0.0/24 -> tw-xconnect.svc.plus
net_prod_dedicated   -> 10.81.0.0/24 -> prod-xconnect-gateway-01
```

这些值只作为当前架构规划示例；修改时必须先改 GitOps，再由渲染器和
workflow 校验。不要把它们复制到 Terraform `*.tfvars`、Vault secret value
或 playbook 默认变量中形成第二事实源。

## 四层职责

### GitOps：非敏感声明

GitOps 保存：

- 网络 ID、CIDR、环境、区域和 provider；
- Gateway/One 的逻辑角色和非敏感服务引用；
- `management_mode`、`lifecycle`、Terraform namespace/state 名称；
- 生产 Gateway 的目标实例名、规格和资源归属；
- 受保护资源的 `external` / `existing-protected` 标记。

GitOps 不保存 API token、密码、WireGuard 私钥、Xray 密钥、SSH 私钥或
Terraform backend 凭据。

推荐的 GitOps 目录和声明入口：

```text
topology/xconnect/network-boundaries.yaml
topology/<env>/hybrid/resource-matrix.json
resources/<project>/<env>/<provider>/*.yaml
```

### Vault：敏感值和连接事实

Vault 保存敏感值；仓库和 Terraform state 只接收运行时注入的变量。当前
XConnect record path 由 GitOps 声明引用，实际值只能从 Vault 读取：

```text
kv/data/prod/ulighthost-xconnect/vault-prod-0
kv/data/prod/ulighthost-xconnect/tw-xconnect.svc.plus
kv/data/prod/ulighthost-xconnect/observability.svc.plus
kv/data/prod/xconnect/prod-xconnect-gateway-01
```

可能出现的敏感字段包括 `ssh_private_key_b64`、密码、WireGuard 密钥、Xray
凭据、XConnect Zero Accounts 凭据、云 provider token 和 state backend
凭据。路径可以被 workflow 用来定位记录，但 secret value 禁止进入 GitOps、
`.tfvars`、plan artifact、CMDB 或日志。

### Ansible playbook：节点配置和运行时接入

Ansible 是 Gateway/One 的配置执行层，负责：

- 从 Vault 读取对应 record；
- 配置 XConnect Zero Gateway 或 One 角色、WireGuard、Xray 和 systemd；
- 将 One 加入指定的网络 ID；
- 写入 Caddy、监控探针和 Accounts 注册配置；
- 验证隧道、心跳、服务入口和回滚状态。

旧 `observability.svc.plus` 节点只在迁移 playbook 中作为 source 使用，不能
因为迁移而进入新的 Terraform state，也不能被 playbook 改名或销毁。

### `iac_modules`：Terraform 资源和 state

本仓库只提供 Terraform provider tree、模块、渲染器和契约测试：

- 对 `existing` 或 `existing-protected` Gateway 只输出引用所需的非敏感事实，
  不创建、不接管、不销毁；
- 对 `net_prod_dedicated` 只有在 GitOps 选择具体 provider/account 后，才由
  相应 provider tree 创建独立 Gateway、网络安全规则和运行时基础资源；
- Terraform 只输出实例 ID、IP、区域、状态等运行时事实，供 CMDB/inventory
  和 Ansible 使用；
- state 使用统一五级 key：

  ```text
  terraform/<env>/<project>/<cloud>/<account>/<workspace>/terraform.tfstate
  ```

- 非 Terraform 的 TW Gateway、PH/TW One 和受保护 `vault-prod-0` 不得出现在
  Terraform state 中。

## 执行顺序

```text
GitOps 网络/资源声明
        ↓
provider renderer（只渲染声明资源）
        ↓
terraform plan / apply（仅 Terraform-managed 资源）
        ↓
CMDB / inventory 输出运行时事实
        ↓
Ansible 从 Vault 读取敏感值并配置 Gateway/One
        ↓
XConnect Zero 网络、心跳、SSH、Caddy、Observability 验证
```

UAT 使用已有 `net_uat` Gateway；不能因为 `target_domains=all` 而为 TW
Gateway 再创建一台 Akamai/AWS/GCP 主机。PROD 的 `net_prod_dedicated` 在
provider/account、区域、规格、成本和 Vault record 就绪前只能执行 plan。

## 必须通过的门禁

1. GitOps 声明中的 `network_id`、`gateway_ref`、provider 和 state namespace
   与环境一致。
2. Terraform plan 不包含 `vault-prod-0`、旧 `observability.svc.plus` 或
   `tw-xconnect.svc.plus` 的 create/update/destroy。
3. external Gateway/One 任务只走 Ansible，不能调用 Terraform apply/destroy。
4. Terraform state key 与 `.tflock` 位于同一个独立 namespace；禁止恢复共享
   `selfhost` state。
5. playbook 只从对应环境/record path 读取 Vault；UAT 不得读取 PROD secret。
6. 任何 destroy 都必须先验证 namespace；`net_security_vault`、旧
   `observability.svc.plus` 和 UAT existing Gateway 永久排除在批量清理之外。

## 与 disposable lab 的关系

`vpn-overlay/xconnect-lab` 是短生命周期的协议/连通性验证工具，不能作为这三张
长期网络的资源声明入口。它可以使用临时 AWS Spot 或 external Gateway 做实验，
但实验 state、Gateway 和 One 均不得替代 GitOps 的 `net_security_vault`、
`net_uat` 或 `net_prod_dedicated` 正式拓扑。
