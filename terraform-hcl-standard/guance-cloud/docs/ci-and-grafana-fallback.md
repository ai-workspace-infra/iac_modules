# CI 编排与 Grafana 回退（#430）

## 职责边界

| 层 | 负责 |
| --- | --- |
| GitOps | 只声明资源（`resources/xworktech.com/uat/guance/observability.yaml`） |
| iac_modules（本目录） | Provider 版本、渲染、受控 plan/apply 脚本、可复用 workflow `.github/workflows/guance-uat.yml`（`workflow_dispatch` + `workflow_call`） |
| platform-ops-toolkit | 通过 `workflow_call` 调用本 workflow，并持有 Vault role 的创建与调度（Vault role 的 `repository` 已允许 `iac_modules` 与 `platform-ops-toolkit` 两种调用方） |

## Workflow：`guance-uat.yml`

| `mode` | 运行的 job |
| --- | --- |
| `offline`（PR 路径触发默认） | `offline`：`offline-check.sh`，无 OIDC、无 Vault |
| `plan` | `offline` → `plan`（environment `uat`，Vault role `…-uat-guance-plan`）；`grafana-fallback` 并行 |
| `apply` | 再加 `apply`（environment `uat-guance-apply`，需评审者批准；role `…-apply`）：plan+guard+apply 同一保存的 plan → `output -json` → CMDB → **第二次 plan 必须为空** → 仅上传 `cmdb.json` |
| `fallback-only` | 只运行 `grafana-fallback` |

`guance_enabled=false` 时所有 Guance job 被跳过，只剩 Grafana 检查，用于演练“停用 Guance 后基础监控仍可用”。

安全约束（均有离线契约测试）：无 `secrets.*` 静态密钥；不使用 `pull_request_target`；仅 `plan`/`apply` 申请 `id-token: write`；`vault-action` 使用 `exportEnv: false`、`exportToken: false`，凭据只在单步 `env` 中出现；Vault 读取集合与 `vault/uat/policies/guance-uat-terraform.hcl` 完全一致；artifact 只含资源 UUID 的 `cmdb.json`。

新增通知对象需同时：manifest 增加条目、Vault 写入 `notify/<id>` 记录、policy 增加该精确路径、workflow `secrets:` 与 `env:` 增加一行（契约测试会提示遗漏）。

## Grafana 回退验证

`scripts/grafana-fallback-check.sh` 访问 `https://observability.svc.plus/grafana/api/health`，要求 HTTP 200 且 `database == "ok"`；脚本不读取任何 Guance/Vault/Terraform 变量。

已执行（2026-10-12，从本次开发会话的沙箱，只读 GET）：`OK: Grafana healthy (version 13.2.3)`。这只证明 Grafana 服务当前存活，**不等于**“停用 Guance 采集写入后基础面板与告警仍有数据”。

### 停用演练（需运维执行，#430 验收）

1. 记录 T0：Grafana 关键面板（Gateway 错误率、Cloud Run 延迟、黄金 API）截图及告警规则状态。
2. 由采集部署 owner（Toolkit/Playbooks）关闭 Guance 写入链路（移除 DataKit/Collector 的 Guance exporter，或撤销 ingest token）；本仓库不执行主机操作。
3. 运行 `gh workflow run guance-uat.yml -f mode=fallback-only -f guance_enabled=false`，确认通过。
4. 等待 ≥ 2 个采集周期，确认 Grafana 面板仍有新数据点、关键告警仍可触发。
5. 恢复链路后对照同一时间窗两侧数据差异，记录到 issue，并整理为季度文章证据。

### Guance 配置回退

GitOps 回退到上一版本 → `uat-terraform.sh plan`（人工检查）→ `apply`。配置回退不恢复遥测历史数据；新资源的删除与通知变更需逐项检查（`plan_guard` 默认拒绝 delete/replace，需 `--allow-delete` 显式放行）。保留 Grafana 关键告警，只有 Guance 告警验证成功才调整通知主入口。
