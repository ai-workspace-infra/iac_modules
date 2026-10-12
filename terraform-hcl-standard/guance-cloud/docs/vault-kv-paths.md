# Guance Vault KV v2 凭据路径契约

状态：规划，尚未写入实际 Vault 或创建 policy。沿用现有 KV v2 mount `kv` 和 UAT/PROD 独立路径、独立 Vault 集群约定。

## 路径与字段

路径中的 workspace 使用稳定逻辑别名，如 `xworktech-uat`，实际 Guance workspace UUID 放 GitOps 配置，不作为易变的路径名称。

| 用途 | Vault CLI 逻辑路径 | 字段 | 消费者 |
| --- | --- | --- | --- |
| Terraform 管理 API | `kv/uat/platform/observability/guance/xworktech-uat/management` | `api_key` | UAT Guance Terraform workflow |
| 只读查询/发布验证 | `kv/uat/platform/observability/guance/xworktech-uat/query` | `api_key` | UAT 验证脚本、OWL/Agent 查询 |
| 遥测写入 | `kv/uat/platform/observability/guance/xworktech-uat/ingest` | `workspace_token` | DataKit/受控 Collector 部署 |
| PROD 管理 API | `kv/prod/platform/observability/guance/xworktech-prod/management` | `api_key` | PROD Guance Terraform workflow |
| PROD 只读查询 | `kv/prod/platform/observability/guance/xworktech-prod/query` | `api_key` | PROD 发布验证/只读查询 |
| PROD 遥测写入 | `kv/prod/platform/observability/guance/xworktech-prod/ingest` | `workspace_token` | PROD 采集部署 |

首期只开 UAT，PROD 路径预留。management 的 API Key、query 的只读 API Key 和采集 workspace token 分别创建、分别轮换，不互相代用；query Key 的只读权限以 Guance 实际授权能力核验。API Key 用于 Guance OpenAPI 的 `DF-API-KEY`；workspace token 用于对应采集协议，不能拿管理 API Key 替代。

Guance endpoint、region、workspace UUID、逻辑别名放 GitOps 非敏感配置。可在各记录增加 `credential_id`、`rotated_at`、`expires_at` 元数据（有真实到期时间才填写），不得包含实际凭据的副本。

## KV v2 路径区别

- CLI 读取：`vault kv get -mount=kv uat/platform/observability/guance/xworktech-uat/management`。
- API / policy / hashicorp vault-action：`kv/data/uat/platform/observability/guance/xworktech-uat/management`。
- 版本管理路径：`kv/metadata/uat/platform/observability/guance/xworktech-uat/management`。

不要把 `data/` 写入 CLI 逻辑 secret 名称；CI 禁止直接打印上述读取命令返回的密钥内容。

## 最小读取 policy（目标样例）

UAT Terraform role 只读取 management，不使用 `platform/*` 通配授权：

```hcl
path "kv/data/uat/platform/observability/guance/xworktech-uat/management" {
  capabilities = ["read"]
}
```

query 与 ingest 使用各自独立 policy，替换为表中对应精确路径。PROD 使用生产路径和独立 auth role。读取角色无需 list、写入、删除或版本销毁权限。state backend 凭据另行读取现有 `kv/data/CICD/<env>/iac_state`，不放进 Guance 记录。

现有宽泛 `platform/*` policy 可能覆盖这些子路径；实施时必须审计角色的全部叠加 policy，确认采集端或查询端不能通过其他 policy 读到 management Key。

GitHub Actions 通过已有 JWT/OIDC 登录 Vault；auth role 绑定仓库、workflow/ref、环境。UAT 与 PROD 分别授权，PROD apply 使用受保护环境。运行时采集器仅获取 ingest 凭据。

## Terraform 与验证工具注入

建议模块变量名 `guance_api_key`，标记 `sensitive = true`，CI 把 management 的 `api_key` 注入 `TF_VAR_guance_api_key`；provider 配置引用该变量。该名称是本仓库拟定契约，不是宣称 Provider 原生环境变量。实现时核验固定 Provider 版本的认证 schema。

query 的 `api_key` 供 OpenAPI 使用 `DF-API-KEY`，OWL 按当前官方版本的 `OWL_TOKEN`/配置接口注入。ingest 的 `workspace_token` 映射到采集器所需配置；映射必须按实际接收协议确认。

禁止经 Terraform Vault data source 读取并输出 secret；管理 Key 仅作为 provider 运行时凭据，不进入 YAML、tfvars、生成 HCL、CMDB 或 Terraform output。Webhook 等资源属性可能进入 state，需按敏感 state 管理，不能把 `sensitive` 当成加密保证。

## 轮换与验收

### Bootstrap 脚本

使用 `scripts/bootstrap-vault-kv.sh`，依赖已配置的 Vault CLI 登录和 `VAULT_ADDR`。脚本通过隐藏输入读取凭据，stdin 写入，默认 CAS=0 防止覆盖已有记录；不创建 KV mount、policy、Guance Key 或 auth role。

```bash
bash scripts/bootstrap-vault-kv.sh --env uat --workspace xworktech-uat --purpose management
bash scripts/bootstrap-vault-kv.sh --env uat --workspace xworktech-uat --purpose query
bash scripts/bootstrap-vault-kv.sh --env uat --workspace xworktech-uat --purpose ingest
```

轮换时提供 Vault 当前版本，例如 `--rotate --expected-version 1`。版本不匹配则写入失败。此脚本写入专用单字段记录，轮换会替换该记录的数据；不要将其他业务字段混入此记录。脚本不会验证 Guance 凭据是否有效，也不会撤销旧 Guance Key，需按下述流程完成。

由管理员或受保护轮换流程创建新 Guance 凭据，写入对应 KV 记录的新版本；先验证只读请求或 UAT plan，再更新消费者，确认成功后撤销旧 Guance 凭据。Vault 历史版本不代表旧 Key 仍有效，不能仅回滚 KV 就宣称完成凭据回退。

验收：UAT role 能读自身指定记录且不能读 PROD；query/ingest role 不能读 management；认证与日志不回显 secret；新 Key 验证通过且旧 Key 撤销；关闭 Guance 链路不影响 Grafana 基础监控。
