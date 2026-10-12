# 验收状态（UAT）

记录日期：2026-10-12。**“离线已验证”只表示契约、渲染、schema 与脚本逻辑通过；任何“线上”项在拿到真实 Guance 工作空间、Vault 授权与凭据前保持“未验收”，不得以模拟结果冒充。**

环境：Terraform 1.10.5、Provider `GuanceCloud/guance` 0.1.0（锁文件校验）、本地 S3 兼容服务（moto）用于 backend 逻辑演练、Python 3.13。

## 总览

| Issue | 离线 | 线上（真实环境） | 阻塞项 |
| --- | --- | --- | --- |
| #425 Vault KV 与凭据 | 已验证 | 未验收 | Vault policy/role 创建；Guance API Key（免费版可能不支持 Open API） |
| #426 Dashboard 渲染与 Provider | 已验证 | 未验收 | 真实 endpoint/region；可用的管理 Key |
| #427 远端 state 与 UAT plan | 已验证（本地 S3 兼容服务） | 未验收 | `kv/CICD/uat/iac_state`、管理 Key；已有资源 UUID 清单 |
| #428 通知对象与告警策略 | 已验证（渲染 + schema + 敏感变量路径） | 未验收 | 测试接收方、触发/恢复通知实测 |
| #429 三个 Monitor 与静默 | 已验证（渲染 + schema + 基线门控） | 未验收 | UAT 实测基线、真实指标名与 DQL、静默到期实测 |
| #430 CI 与 Grafana 回退 | 已验证（workflow 契约、回退脚本） | 部分：Grafana 健康检查已对真实端点只读执行一次 | GitHub environments、Vault role、关闭 Guance 写入的演练 |
| #431 PROD 门禁 | 已验证（门禁脚本、PROD 渲染被拒绝） | 不适用，**未授权** | UAT 全量实测、独立 workspace/凭据/state、明确授权 |

## 逐项证据

### #425
- 离线已验证：脚本以 stdin 传值、不回显、Vault 错误被抑制；CAS=0 防覆盖；错误版本轮换失败；`notify` 记录；Vault policy 精确只读且用途互不相读；UAT policy 不含 PROD 路径；OIDC role 绑定 workflow 与 environment。（`tests/test_bootstrap_vault_kv.py`、`tests/test_vault_contract.py`）
- 未验收：服务端实际授权（UAT role 读 PROD 被拒、query/ingest 读 management 被拒）、叠加 policy 审计、Key 创建/轮换/撤销、日志不回显。
- 已核验事实：Provider 原生读取 `GUANCE_ACCESS_TOKEN`（缺失时报错，设置后进入 plan），文档契约已据此更新。

### #426
- 离线已验证：YAML → Python/Jinja2 → 显式 HCL（每资源一个命名块，无 `for_each/count/dynamic/templatefile`）；`terraform fmt` 无差异；`init -backend=false` + `validate` 通过；输出 `cmdb_runtime` → `cmdb.json`（只含 id/name/type/environment/workspace_alias/uuid/workspace_uuid，校验与 manifest 一致）；渲染产物被 `.gitignore` 忽略；渲染确定性。
- 未验收：真实 apply 后的 UUID、`template_info` 与 API 回读是否产生非预期差异。
- 与 PR #432 初版的差异：Dashboard `template_info` 由 JSON 字符串改为 `jsonencode({...})` 显式对象；`provider` 不再含凭据变量。

### #427
- 离线已验证：以 moto 提供的 S3 兼容服务完成 `init`（partial backend，key 为 `terraform/uat/xworktech.com/guance-cloud/xworktech-uat/observability/terraform.tfstate`）、`validate`、`plan`（7 个 create，0 change/delete），凭据未写入 `.terraform/`；`plan_guard` 拦截 delete/replace、未评审的 import 差异、非空二次 plan；`import {}` 块显式渲染。
- 未验收：对真实 bucket/锁文件的 init；对真实工作空间的 import；apply 后第二次 plan 为空；人工修改后的漂移检测。

### #428
- 离线已验证：`opt_set` 只能来自 sensitive 变量；manifest 拒绝凭据键/值；plan 文本在含凭据形态时被抑制；plan JSON 仅经 `plan_guard` 汇总（不含属性值）。
- 依据 Provider `v0.1.0` 源码：refresh 时 `opt_set` 会按 Go `json.Marshal` 规范化，已改为渲染 `jsonencode(jsondecode(var.…))` 并实测输出一致；API 是否对 secret 打码待实测。
- 已知限制：`opt_set` 在 Provider 0.1.0 schema 中非 sensitive 属性，apply 后明文进入 state；已在运行手册规定 state 访问与不上传 plan 的缓解措施。
- 未验收：测试接收方的触发与恢复通知、告警 `status` 取值（`ok`/`nodata`）、`checker_uuids` 与 `alert_policy_uuids` 的真实关联行为。

### #429
- 离线已验证：3 个 Monitor 展开为显式块；`baseline: pending` 时渲染为停用（`status = 2`），`measured` 才启用且不得含 `REPLACE_` 占位；静默必须限定告警策略与事件 tags、一次性、≤ 8 小时、结束晚于开始。
- 未验收：真实指标/DQL 与阈值基线（示例清单为合成占位）、失败与恢复模拟、静默到期后告警恢复、漂移检测。

### #430
- 离线已验证：workflow 契约（无静态 secrets、仅 plan/apply 获取 OIDC、Vault 读取与 policy 一致、apply 受保护 environment、二次 plan 必须为空、仅上传 CMDB）；Grafana 回退脚本的成功/失败路径与不依赖 Guance 变量。
- 已执行（只读）：`https://observability.svc.plus/grafana/api/health` → `database: ok`，version 13.2.3（2026-10-12）。
- 未验收：GitHub Actions 实际运行、Vault OIDC 登录、关闭 Guance 写入后的 Grafana 数据对照与告警（演练步骤见 [ci-and-grafana-fallback.md](ci-and-grafana-fallback.md)）。

### #431
- 离线已验证：`prod_gate.py` 要求 8 项 UAT 实测证据、独立 workspace/凭据/state、独立 plan 评审与明确授权；示例记录必然被拒绝；`generate.py` 拒绝 `environment: prod`；仓库不含 PROD apply workflow。
- 未验收/未授权：PROD 一切。

## 跨 issue 的首要阻塞

官方版本对比写明免费版**不支持通过 Open API 获取和更新工作空间数据**，而 Provider 依赖 API Key 调用 OpenAPI（详见 [free-tier-constraints.md](free-tier-constraints.md)）。在用真实免费工作空间验证 API Key 之前，#425–#429 的线上验收可能无法完成。需要用户确认：UAT 使用商业/试用工作空间，或接受免费版仅能控制台管理。
