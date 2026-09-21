# Akamai UAT 六 namespace state 迁移

当前共享 `selfhost` state 必须退役。目标是六个互不共享锁、计划和销毁范围的
Terraform state：

| namespace | 用途 | 清理策略 |
|---|---|---|
| `web-saas` | `console-selfhost-uat.onwalk.net` 全栈 | 迁移验收后可按 state 清理 |
| `open-platform` | 新节点上的 Observability + Vault | 常驻，默认禁止 destroy |
| `ai-workspace` | xworkmate 套件，SG 4C8G | 迁移验收后可按 state 清理 |
| `agent-proxy-jp` | JP Agent Proxy | 迁移验收后可按 state 清理 |
| `agent-proxy-us` | US Agent Proxy | 迁移验收后可按 state 清理 |
| `agent-proxy-sg` | SG Agent Proxy | 迁移验收后可按 state 清理 |

state key 固定为：

```text
terraform/uat/platform-ops-toolkit/akamai-cloud/<真实账户名>/<namespace>/terraform.tfstate
```

可以在不读取任何凭据的情况下检查 key：

```bash
python3 terraform-hcl-standard/akamai-cloud/scripts/state_contract.py \
  --account '<真实账户名>' \
  --namespace web-saas
```

## 迁移门禁

1. 记录旧 `selfhost` key、S3 object version、`terraform state list` 和 Linode ID。
2. 禁止对旧 state 执行 apply/destroy。为六个 GitOps 声明分别渲染到对应 workdir。
3. 把每台实例及其 firewall 导入对应新 state；导入期间不得修改云资源。
4. 账号级 SSH key 不复制到六个 state。新配置直接把非敏感 SSH 公钥传给实例；旧
   `linode_sshkey` 在迁移记录确认后从旧 state 解除管理，不在迁移期间删除云端对象。
5. 每个新 state 依次执行 `terraform validate`、`terraform plan -detailed-exitcode`；
   只有退出码 0（0 add / 0 change / 0 destroy）才可继续。
6. 完成 Vault 数据备份/恢复演练、Observability 数据核对和服务健康检查后，才能
   切换 DNS。旧 `ssh ubuntu@observability.svc.plus` 始终是外部迁移源和回滚源，
   不得 import、修改或销毁。
7. 观察期完成后，封存旧 `selfhost` state；不得继续把它作为运行入口。

## 受控清理

清理必须逐个显式选择以下五个 namespace：

```text
web-saas
ai-workspace
agent-proxy-jp
agent-proxy-us
agent-proxy-sg
```

任何包含 `open-platform`、`selfhost`、`all`、`shared` 或多个 namespace 的 destroy
都必须失败。每次 destroy 前保存 plan 并核对资源地址/实例 ID；完成后重新读取
`open-platform` state，并检查 `observability.svc.plus`、`vault.svc.plus` 健康。

本文只定义迁移与验收契约，不授权跳过审批直接执行云端 apply/destroy。
