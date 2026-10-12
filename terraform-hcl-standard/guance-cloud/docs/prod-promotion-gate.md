# PROD 推广门禁（#431）

**当前状态：未授权。** 没有 UAT 实测验收与明确授权时，不执行任何 PROD apply。本仓库**不包含** PROD apply workflow；`generate.py` 只接受 `environment: uat`，传入 `prod` 会被拒绝。

## 门槛

1. **独立隔离**（不得复用 UAT）
   - Workspace：独立别名，如 `xworktech-prod`。免费版每个用户只能创建 1 个工作空间，因此 PROD 需要独立账号/商业版。
   - 凭据：独立的 management/query/ingest 记录 `kv/prod/platform/observability/guance/xworktech-prod/{management,query,ingest}`，独立 Vault policy 与 role（environment `prod`，受保护且需评审者批准）。
   - State：`terraform/prod/<project>/guance-cloud/<prod_alias>/observability/terraform.tfstate`（由 `state_contract.py` 生成，与 UAT key 不同）。
2. **UAT 实测验收**：`scripts/prod_gate.py` 要求下列每项为 `verified`，并附日期、验证人、GitHub issue/PR/run 证据链接；`offline-only` 一律不通过：
   `vault_kv_and_oidc`、`dashboard_render_and_apply`、`remote_state_and_stable_plan`、`notify_and_alert_policy`、`monitors_and_mute`、`ci_and_grafana_fallback`、`cost_and_quota`、`rollback_rehearsed`。
3. **独立 plan 评审**：PROD plan 无 delete/replace，评审人不同于申请人。
4. **明确授权**：`authorization.scope = "prod-apply"`，批准人不同于申请人，指向 GitHub issue 评论。
5. **低风险流量验证与生产回退**：先只部署 Dashboard 与停用状态的 Monitor；用低风险流量验证数据与告警；回退按 UAT 演练过的流程（GitOps 回退 → render → plan → apply；保留 Grafana 关键告警）。

## 使用

```bash
cp docs/prod-acceptance.example.json /secure/location/prod-acceptance.json   # 填写真实证据，不入库
python3 scripts/prod_gate.py --record /secure/location/prod-acceptance.json
```

退出码非 0 即阻止后续 PROD 步骤。示例文件所有门槛均为 `pending`，必定被拒绝。门禁通过只是签收证据，不会自动部署；PROD workflow 需要在授权后另行评审添加，并在第一步调用本脚本。
