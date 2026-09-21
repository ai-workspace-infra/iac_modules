# Vault KV v2 路径规划

Vault 由 Open Platform 管理，但 UAT 与 PROD 使用独立集群和独立根路径。
以下路径以 KV v2 mount `kv` 为准；文档只记录路径和字段契约，不记录实际密钥值。

## 路径布局

```text
kv/CICD/<env>/gcp-bootstrap/<gcp_account_id>
kv/CICD/<env>/iac_state
kv/<env>/platform/oidc
kv/<env>/platform/jwt
kv/<env>/platform/cloudflare
kv/<env>/platform/gcp
kv/<env>/platform/observability
kv/<env>/platform/gitea
kv/<env>/services/xconnect
kv/<env>/services/ai-workspace
```

`<env>` 只能是 `uat` 或 `prod`，`<gcp_account_id>` 使用可读的账号标识（例如
`xworktech`）。禁止使用 `kv/shared/*` 保存环境凭据；真正共享
的非机密配置放 GitOps，机密必须复制到两个环境的对应路径并分别轮换。

Open Platform 的环境映射固定为：

| 环境 | GCP 项目 | Vault 集群 |
| --- | --- | --- |
| UAT | `xwork-open-platform-uat` | UAT 单节点或小型 Raft 集群 |
| PROD | `xwork-open-platform-prod` | 3 节点 Raft 集群（`asia-east1-a/b/c`） |

## 字段契约

| 路径 | 字段 |
| --- | --- |
| `kv/CICD/<env>/gcp-bootstrap/<gcp_account_id>` | `GCP_ACCESS_TOKEN`, `GCP_PROJECT_ID` |
| `kv/CICD/<env>/iac_state` | `TF_STATE_ENDPOINT`, `TF_STATE_BUCKET`, `TF_STATE_ACCESS_KEY`, `TF_STATE_SECRET_KEY`, `TF_STATE_REGION` |
| `kv/<env>/platform/oidc/<gcp_account_id>` | `gcp_workload_identity_provider`, `gcp_oidc_audience`, `deploy_service_account`, `project_id` |
| `kv/<env>/platform/jwt` | `issuer`, `audience`, `signing_key` |
| `kv/<env>/platform/cloudflare` | `api_token`, `account_id`, `zone_id` |
| `kv/<env>/platform/gcp` | `project_id`, `region`, `artifact_registry` |
| `kv/<env>/platform/observability` | `grafana_admin_password`, `remote_write_token` |
| `kv/<env>/platform/gitea` | `url`, `runner_token`, `webhook_secret` |
| `kv/<env>/services/xconnect` | `supabase_url`, `supabase_service_role`, `jwt_audience` |
| `kv/<env>/services/ai-workspace` | `api_base_url`, `oauth_client_secret`, `jwt_audience` |

## Policy 边界

- `github-actions-*-uat` 只能读取 `kv/data/uat/platform/*` 和被明确 allowlist 的
  `kv/data/uat/services/*` 路径。
- `github-actions-*-prod` 只能读取 `kv/data/prod/platform/*` 和生产 allowlist，
  不得读取 UAT 路径。
- 应用运行时 service account 只读取自身服务路径和必要的 `platform/jwt` 公钥材料。
- 写入、删除和轮换由 Vault 管理员或受保护的轮换 workflow 执行。
- GitHub Actions 日志中禁止输出 Vault response、JWT、token 和完整路径值。

## Terraform / Ansible 对接

Terraform 输出 WIF provider、OIDC audience、service account 和 project ID；bootstrap
workflow 在成功 apply 后将这些值写入对应环境的
`<env>/platform/oidc/<gcp_account_id>` 路径。Terraform backend 使用统一的
`CICD/<env>/iac_state` 配置，不为每个云重复创建 state 服务；云、环境和 workspace
仍由 backend key 隔离。首次 bootstrap 所需的短期凭据单独放在
`CICD/<env>/gcp-bootstrap/<gcp_account_id>`，不写入 runtime OIDC 路径。
Vault policy 和 auth role 由管理员或受保护 workflow 管理，Terraform 不直接写入
bootstrap secret value。

每次新增字段都要同时更新：

1. 本文件的字段契约；
2. 对应 Vault policy；
3. Ansible role 的 check-mode 校验；
4. GitHub Actions 的最小读取 allowlist。
