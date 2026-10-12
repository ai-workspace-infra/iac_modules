# Guance UAT workdir

声明输入：GitOps `resources/xworktech.com/uat/guance/observability.yaml`（字段示例见 `../../tests/fixtures/uat-observability.yaml`，合成数据）。**尚未部署，尚未验收**；状态见 [../../docs/acceptance-status.md](../../docs/acceptance-status.md)。

```bash
# 离线（无凭据）：渲染 + fmt + validate + 契约测试
bash ../../scripts/offline-check.sh --manifest /path/to/observability.yaml

# 受控 plan / apply（凭据由 Vault 注入环境变量，见 ../../docs/uat-runbook.md）
bash ../../scripts/uat-terraform.sh plan --resources /path/to/observability.yaml --workdir .
```

Provider 固定 `GuanceCloud/guance = 0.1.0`；管理 API Key 经 `GUANCE_ACCESS_TOKEN`（Provider 原生变量）注入，通知对象 `opt_set` 经 `TF_VAR_guance_notify_<id>_opt_set` 注入。backend 为统一的 S3 兼容 state（`TF_STATE_*`），key 由 `generate.py state-key` 生成。不要将凭据放入清单、tfvars 或命令参数；本目录只入库 `README.md` 与 `.gitignore`。
