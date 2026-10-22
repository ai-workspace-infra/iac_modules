# Guance Cloud Terraform（UAT）

状态：UAT 的 Vault 凭据契约、渲染器、受控 plan/apply、CI 与 PROD 门禁**已有代码和离线验证**；**没有任何真实 Guance 工作空间、Vault 或远端 state 的验收**。逐项结果与阻塞见 [docs/acceptance-status.md](docs/acceptance-status.md)。首要风险：官方文档称免费版不支持通过 Open API 管理工作空间数据，Provider 依赖 API Key，见 [docs/free-tier-constraints.md](docs/free-tier-constraints.md)。

本目录遵循上级 `AGENTS.md` 和 `../../skills/terraform-yaml-render-pattern/SKILL.md`：

```
GitOps YAML ──generate.py render──▶ 显式 HCL（每资源一个命名块，无 for_each/count/dynamic）
                                         │ terraform apply（官方 GuanceCloud/guance = 0.1.0）
                                         ▼
             cmdb.json ◀──generate.py inventory── terraform output cmdb_runtime（仅 uuid/workspace_uuid）
```

Terraform 管理观测配置；现有 `observability.svc.plus/grafana/` 继续提供基础监控与回退，不假设数据源或面板可一键迁移。

## 任务与文档

看板：[Multi Cloud IAC 对接与 Landing Zone](https://github.com/orgs/ai-workspace-infra/projects/2)。

| Issue | 内容 | 主要文件 |
| --- | --- | --- |
| [#425](https://github.com/ai-workspace-infra/iac_modules/issues/425) | Vault KV、最小权限、OIDC、轮换 | `docs/vault-kv-paths.md`、`scripts/bootstrap-vault-kv.sh`、`vault/uat/` |
| [#426](https://github.com/ai-workspace-infra/iac_modules/issues/426) | YAML → HCL → CMDB | `scripts/generate.py`、`guance_manifest.py`、`hcl.py`、`templates/` |
| [#427](https://github.com/ai-workspace-infra/iac_modules/issues/427) | 统一远端 state、受控 plan、import | `templates/backend.tf`、`scripts/state_contract.py`、`tf-init.sh`、`uat-terraform.sh`、`plan_guard.py` |
| [#428](https://github.com/ai-workspace-infra/iac_modules/issues/428) | 通知对象、告警策略 | manifest `notify_objects`/`alert_policies`、`docs/uat-runbook.md` |
| [#429](https://github.com/ai-workspace-infra/iac_modules/issues/429) | 三个 Monitor、发布静默 | manifest `monitors`（基线门控）/`mutes`（范围与时长限制） |
| [#430](https://github.com/ai-workspace-infra/iac_modules/issues/430) | CI 编排、Grafana 回退 | `../../.github/workflows/guance-uat.yml`、`scripts/grafana-fallback-check.sh`、`docs/ci-and-grafana-fallback.md` |
| [#431](https://github.com/ai-workspace-infra/iac_modules/issues/431) | PROD 门禁（未授权） | `docs/prod-promotion-gate.md`、`scripts/prod_gate.py`、`envs/prod/` |

规划背景见 [docs/first-batch-resources-plan.md](docs/first-batch-resources-plan.md)。官方 Provider：[GuanceCloud/terraform-provider-guance](https://github.com/GuanceCloud/terraform-provider-guance)；schema 核验自 0.1.0 发布版（`terraform providers schema`）。

## 目录

```text
guance-cloud/
  scripts/   generate.py（render | inventory | import | state-key）、guance_manifest.py、hcl.py、
             state_contract.py、tf-env.sh、tf-init.sh、uat-terraform.sh、plan_guard.py、secret_scan.py、
             hcl_policy.py、offline-check.sh、grafana-fallback-check.sh、prod_gate.py、bootstrap-vault-kv.sh
  templates/ provider.tf  variables.tf  backend.tf  resources.tf.j2  imports.tf.j2
  vault/uat/ policies/*.hcl  roles/*.yaml            # 精确只读 policy 与 OIDC role 规格（未写入 Vault）
  tests/     unittest 契约测试 + 合成 fixture
  envs/uat/  envs/prod/                              # 仅 README.md + .gitignore
  docs/
```

资源直接渲染为显式 `resource` 块，未抽取 `modules/`：目前无跨 env 复用，且子模块需要重复声明 Provider schema；PROD 获授权后再按复用需求评估（子模块必须声明 `required_providers`）。

## 常用命令

```bash
python3 -m pip install -r requirements.txt           # 建议独立 venv；Terraform >= 1.10
bash scripts/offline-check.sh                        # 无凭据的 UAT 离线检查
python3 -m unittest discover -s tests                # 仅契约测试
python3 scripts/generate.py state-key --resources MANIFEST
```

受控 plan/apply、import、漂移检测见 [docs/uat-runbook.md](docs/uat-runbook.md)。

## 安全约束

- 凭据只经 Vault/环境变量：管理 Key → `GUANCE_ACCESS_TOKEN`；通知 `opt_set` → `TF_VAR_guance_notify_<id>_opt_set`；state → `TF_STATE_*`（映射为 `AWS_*` 仅供 Terraform 进程）。不写入 Git、YAML、tfvars、Terraform output 或日志。
- manifest 拒绝凭据键与凭据形态的值；`secret_scan.py` 扫描源码和渲染产物。
- plan 文件和 plan JSON 含明文，仅在私有临时目录经 `plan_guard.py` 汇总后销毁；state 视为敏感数据。
- Terraform 资源 identity 为 manifest `id`；`plan_guard` 默认拒绝任何 delete/replace。
