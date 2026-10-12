# UAT 运行手册：渲染、import、plan、验证

所有命令在 `terraform-hcl-standard/guance-cloud/` 下执行。凭据只用环境变量/Vault 注入，不写入文件、命令行或日志。需要 Terraform ≥ 1.10（`use_lockfile`）。

## 0. 离线检查（无需凭据）

```bash
python3 -m pip install -r requirements.txt
bash scripts/offline-check.sh [--manifest /path/to/observability.yaml]
```

覆盖：契约测试、渲染、HCL 禁用控制结构检查、`terraform fmt`/`init -backend=false`/`validate`（固定 Provider 0.1.0 schema）、凭据形态扫描、产物 `.gitignore`。**不证明**任何真实工作空间行为。

## 1. 声明

GitOps `resources/xworktech.com/uat/guance/observability.yaml`。字段见 `tests/fixtures/uat-observability.yaml`（合成示例）。要点：

- `notify_objects` 只声明 `id/name/type`；`opt_set`（webhook、secret、收件人）**永远**来自 Vault，经 `TF_VAR_guance_notify_<id>_opt_set` 注入，manifest 中出现 `opt_set/token/secret/webhook` 等键或凭据形态的值会被拒绝。
- `monitors[].baseline.status: pending` 时渲染为 `status = 2`（停用）。只有在填写 `measured`（`measured_at/window/source/summary`）并去掉所有 `REPLACE_` 占位后，才渲染为启用。
- `mutes[]` 必须限定告警策略与事件 `tags`，一次性窗口 ≤ 8 小时，不允许重复规则或空范围；到期自动结束，窗口随发布 PR 在 GitOps 中变更。

## 2. 受控 plan

```bash
export GUANCE_ACCESS_TOKEN=...            # management 记录，Provider 原生变量
export TF_VAR_guance_notify_uat_test_receiver_opt_set=...   # notify 记录
export TF_STATE_ENDPOINT=... TF_STATE_BUCKET=... TF_STATE_ACCESS_KEY=... TF_STATE_SECRET_KEY=... TF_STATE_REGION=...
bash scripts/uat-terraform.sh plan --resources "$MANIFEST" --workdir envs/uat
```

State key 由契约生成：`terraform/uat/<project>/guance-cloud/<workspace_alias>/observability/terraform.tfstate`（`generate.py state-key` 可单独查看）。脚本把 plan 写入私有临时目录，`plan_guard.py` 只输出地址与动作，**发现 delete/replace 立即失败**；plan 文件、plan JSON 含明文，不上传、不留存。

## 3. 已有资源 import

1. 在控制台/API 盘点已有对象，写成一个**不入库**的 JSON：`{"uat_service_overview": "<dashboard uuid>"}`。
2. `bash scripts/uat-terraform.sh plan ... --existing existing.json` 生成显式 `import {}` 块。
3. plan 若显示被导入对象与声明有差异（update），`plan_guard` 默认失败，需人工比对后加 `--allow-import-updates`。
4. apply 后删除 `existing.json`；`generated_imports.tf` 为派生物，不入库。

## 4. 重复 plan 与漂移

apply 之后立即：`bash scripts/uat-terraform.sh plan --expect-no-changes ...`，任何 create/update/delete/import 都判失败。控制台手工修改一项后再次运行，应当看到该项 update（漂移检测）。

## 5. 敏感属性与 state

`opt_set` 在 Provider 0.1.0 schema 中不是 sensitive 属性，`template_info_export` 为 sensitive 但仍明文进入 state。Terraform 的 `sensitive` 只隐藏输出，不加密 state。因此：

- state bucket 只授予 `kv/CICD/uat/iac_state` 对应凭据，禁止把 state、plan、`terraform show -json` 作为 artifact 上传或贴入 issue。
- `opt_set` 渲染为 `jsonencode(jsondecode(var.…))`，与 Provider refresh 时的规范化结果一致；Vault 中的值必须是合法 JSON 对象（非法时 plan 报错，且不回显该值）。
- 通知对象只用测试接收方；轮换 webhook 时先在 Vault 写新版本，再 apply，最后撤销旧 webhook。
- CI 日志只含地址和动作；`uat-terraform.sh` 在 plan 文本含凭据形态时拒绝输出。

## 6. 通知验证（#428，需真实工作空间）

1. 仅向测试接收方配置 `uat_test_receiver`，策略 `status` 含 `ok` 以接收恢复通知。
2. 将某 Monitor 的阈值临时设为必触发值（GitOps PR），apply，确认收到**触发**通知；恢复阈值，确认收到**恢复**通知。
3. 记录事件 ID/时间与通知截图（不含 webhook），写入对应 issue。

## 7. Monitor 基线（#429，需真实数据）

1. 在 Guance 对 Gateway 5xx、Cloud Run P95、黄金 API 探测各取 ≥ 7 天（免费版保留期上限）数据，导出分位数/最大值。
2. 阈值 = 基线外加余量，写入 `baseline.summary`（数据窗口、来源、分位数、余量理由）。
3. 将 `baseline.status` 改为 `measured`，去掉 `REPLACE_`，PR 评审后 apply，状态变为启用。
4. 模拟失败与恢复，记录 Monitor 事件与通知。

## 8. 发布静默（#429）

在发布 PR 中新增 `mutes[]` 条目（≤ 8h、限定策略与服务 tags）。验证：窗口内目标事件被静默；窗口结束后同类事件恢复通知。过期条目在后续 PR 中移除（plan 会出现 delete，需 `--allow-delete guance_mute.<id>` 显式放行）。
