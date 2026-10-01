# UAT Hybrid 多云资源矩阵

本文记录 UAT/PROD 的目标资源矩阵，不表示当前 GitOps 声明、工作流或真实资源已全部
达到此状态。运行时必须读取对应环境的 GitOps 声明；本文中的示例不得成为 Toolkit
固定矩阵或自动创建资源的依据。端到端验收需另附 Terraform plan、实例事实及 workflow run。

`open-platform-shared` 独立于两个环境的
Hybrid 业务矩阵，不因为业务发布、停止或清理而被删除。

## 生命周期边界

`open-platform-shared`（Vault、Observability、IAM）是独立的共享平台生命周期，不属于
Hybrid 业务矩阵的串行业务步骤。Hybrid 只消费已经就绪的平台服务；平台资源不得因为
业务域停止或重跑而被删除。

## 共享平台

| Namespace | 管理模式 | Provider | 生命周期 | 说明 |
|---|---|---|---|---|
| `open-platform-shared` | 独立平台编排 | GCP | 常驻，禁止业务矩阵 destroy | 提供 Vault、Observability、IAM；由独立 platform orchestrator 管理 |

共享项目名称为 `open-platform-shared`，实际 GCP project ID 为
`open-platform-shared-510113`。三个资源使用独立 namespace/state：

- `open-platform-shared-vault`
- `open-platform-shared-observability`
- `open-platform-shared-iam`

Daily Snapshot 仅依次检查 Vault、Observability、IAM 服务就绪，不触发其部署、升级或
迁移。共享平台变更由独立 `open-platform-orchestrator.yml` 调度对应服务 workflow。
业务发布成功不等于共享平台迁移已验收。

## 声明与状态边界

- 非敏感资源、provider、account、区域和生命周期：GitOps。
- 敏感凭据：Vault KV；统一 state 参数入口为 `kv/data/CICD/<env>/iac_state`。
- Terraform renderer 与资源模块：`iac_modules`，按声明选择云厂商。
- 主机配置与健康检查：Playbooks；调度、审批与发布证据：Toolkit。
- 独立 backend key：`terraform/<env>/<project>/<provider>/<account>/<namespace>/terraform.tfstate`；
  锁文件为该 key 后追加 `.tflock`。`project` 是 GitOps 逻辑项目，不可与 GCP project ID 混淆。
- provider/account 变化不允许隐式迁移或丢弃旧 state；先盘点、备份、一对一映射和审核 plan。
- 本文合并不授权真实 apply、destroy、DNS 切换或数据迁移。

## UAT 业务矩阵

| 顺序 | Namespace | 管理模式 | Provider / 资源类型 | 规格与生命周期 | 说明 |
|---:|---|---|---|---|---|
| 1 | `web-saas` | Existing + Serverless | GCP 持久节点 + Serverless | 持久节点可 stop/start，不允许删除 | 使用 `open-platform-shared` 服务；不得复用生产 `vault-prod-0` |
| 2 | `ai-workspace` | Terraform | GCP Spot | 4C，最长 1 小时 | UAT 临时 Spot 资源 |
| 3 | `agent-proxy-jp` | Terraform | AWS Spot | 2C2G，最长 1 小时 | JP Gateway/Proxy/CPA 混合部署 |
| 4 | `agent-proxy-us` | Terraform | GCP Spot | 2C2G，最长 1 小时 | US Gateway/Proxy/CPA 混合部署 |
| 5 | `agent-proxy-sg` | Terraform | GCP Spot | 2C2G，最长 1 小时 | SG Gateway/Proxy/CPA 混合部署 |

## PROD 业务矩阵

| 顺序 | Namespace | 管理模式 | Provider / 资源类型 | 规格与生命周期 | 说明 |
|---:|---|---|---|---|---|
| 1 | `web-saas` | Existing + Serverless | GCP 持久节点 + Serverless | 持久节点可 stop/start，不允许删除 | 使用 `open-platform-shared` 服务；不复用生产 `vault-prod-0` 作为 Web SaaS 节点 |
| 2 | `ai-workspace` | Terraform | GCP Spot | 4C8G，最长 1 小时 | PROD 也使用独立 Spot state，不复用 `10.79.0.7` |
| 3 | `agent-proxy-jp` | Terraform | AWS 持久节点 | 2C2G，禁止 destroy | JP Gateway/Proxy/CPA 混合部署 |
| 4 | `agent-proxy-us` | Terraform | GCP 持久节点 | 2C2G，禁止 destroy | US Gateway/Proxy/CPA 混合部署 |
| 5 | `agent-proxy-sg` | Terraform | Akamai Cloud 持久节点 | 2C2G，禁止 destroy | SG Gateway/Proxy/CPA 混合部署 |
| 6 | `agent-proxy-tw` | Existing | Ulighthost | 复用现有节点 | 不进入 Terraform state，由 external-node workflow 管理 |
| 7 | `agent-proxy-ph` | Existing | Ulighthost | 复用现有节点 | 不进入 Terraform state，由 external-node workflow 管理 |

## 关键约束

- `web-saas` 的 GCP 持久节点可以执行显式 stop/start，但任何自动清理或 `destroy` 都必须
  被拒绝；如由 Terraform 管理，必须设置 `prevent_destroy`。
- `vault-prod-0` 是生产 Vault 主节点和 XConnect Gateway，禁止被 UAT 复用、接管、改名或销毁。
- UAT 的 `ai-workspace` 是 GCP Spot，规格 4C，最长 1 小时；PROD 的
  `ai-workspace` 是独立 GCP Spot，规格 4C8G，最长 1 小时。
- UAT 的 JP/US/SG 是最长 1 小时的 Spot；PROD 的 JP/US/SG 是持久 Terraform 节点，
  必须禁止 destroy。
- PROD 的 Web SaaS 持久节点允许显式 stop/start，但任何自动清理或 `destroy` 都必须被拒绝。
- JP/US/SG 必须使用矩阵指定的 provider/account/profile；不能由 `target_domains=all` 的
  默认 provider 覆盖为同一个云。UAT 的 SG 使用 GCP，PROD 的 SG 使用 Akamai Cloud。
- TW/PH 只在 PROD 业务矩阵中读取 GitOps external inventory，不执行 Terraform create/apply/destroy。
- `operation=deploy` 默认不执行迁移；只有显式 `operation=migrate` 或
  `operation=deploy+migrate` 才能调用迁移 job。
- `observability` agent 默认接入 `https://observability.svc.plus/`，Accounts/XConnect
  Gateway 地址从 GitOps/Vault 配置读取，不写死在 workflow matrix 中。

## Hybrid 执行顺序

1. 检查 `open-platform-shared` 服务健康，不在 Hybrid 中申请或删除共享平台资源。
2. 按当前环境矩阵部署或唤醒 `web-saas` 的持久节点，并调度 Serverless 组件。
3. 按环境矩阵创建 GCP Spot `ai-workspace`；UAT 为 4C，PROD 为 4C8G，均最长 1 小时。
4. UAT 创建 JP/US/SG Spot 节点；PROD 创建并持久管理 JP/US/SG 节点。
5. 仅在 PROD 读取并部署 Ulighthost TW/PH existing 节点。
6. 汇总各 namespace 的 inventory、监控心跳、Accounts 注册和 XConnect 连通性。

## 验收与清理

- 业务节点验证必须区分 `stopped`、`running`、`terminated`；停止持久节点不等于销毁。
- UAT 只允许清理显式声明的 UAT Spot namespace；不得批量清理 `open-platform-shared` 或
  `web-saas` 持久节点。
- PROD 只允许清理显式声明的 `ai-workspace` Spot namespace；不得清理
  `open-platform-shared`、`web-saas` 持久节点、PROD JP/US/SG 持久节点、TW/PH existing
  或生产 Vault。
- 每次 `plan/apply` 必须输出 provider、account、namespace、实例名称、区域、Spot 到期策略，
  并验证 Terraform state key 与目标云账号一致。
