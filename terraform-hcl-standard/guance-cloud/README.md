# Guance Cloud Terraform 目标结构

状态：已实现 Vault KV bootstrap、UAT Dashboard YAML/Jinja2 渲染与运行事实 CMDB 合并；其余资源模块按任务推进。使用官方 Provider 0.1.0 的离线生成配置已通过 Terraform validate；尚未部署远端资源。

安装渲染依赖：`python3 -m pip install -r requirements.txt`（建议使用独立 venv）。Dashboard 目前由模板生成显式 resource，后续再提取复用 module；静默与通知等尚未实现。

## 最小任务跟踪

看板：[Multi Cloud IAC 对接与 Landing Zone](https://github.com/orgs/ai-workspace-infra/projects/2)。

1. [#425 Vault KV 与权限验收](https://github.com/ai-workspace-infra/iac_modules/issues/425)
2. [#426 UAT Dashboard 渲染与 Provider 验证](https://github.com/ai-workspace-infra/iac_modules/issues/426)
3. [#427 远端 state 与 UAT plan](https://github.com/ai-workspace-infra/iac_modules/issues/427)
4. [#428 通知对象与告警策略](https://github.com/ai-workspace-infra/iac_modules/issues/428)
5. [#429 三个 Monitor 与发布静默](https://github.com/ai-workspace-infra/iac_modules/issues/429)
6. [#430 CI 编排与 Grafana 回退](https://github.com/ai-workspace-infra/iac_modules/issues/430)
7. [#431 PROD 推广门禁](https://github.com/ai-workspace-infra/iac_modules/issues/431)

本批验证为离线 schema 与生成契约验证；不代表真实工作空间、查询语义、告警、Vault 或免费专区兼容性验收。

本目录遵循上级 `AGENTS.md` 和 `../../skills/terraform-yaml-render-pattern/SKILL.md`：GitOps YAML 为资源的唯一人工声明入口，Python/Jinja2 展开显式 HCL，env 只保存 README 与忽略规则；生成文件不入库。Terraform 管理观测配置，现有 Grafana/OTel/Vector 继续提供基础采集与回退。

## 目标目录（待实现）

```text
guance-cloud/
  README.md
  docs/
    first-batch-resources-plan.md
  scripts/
    generate.py                   # render + inventory，共享入口
  templates/
    provider.tf                   # GuanceCloud/guance，版本锁定
    variables.tf
    backend.tf                    # 复用组织统一 state 契约
    resources.tf.j2               # 展开显式 module 块
    outputs.tf.j2                 # 资源 UUID 等运行时事实
  modules/
    dashboard/
    monitor/
    alert_policy/
    notify_object/
    mute/
  envs/
    uat/                          # README.md + .gitignore
    prod/                         # README.md + .gitignore
```

资源声明位于 GitOps 仓库 `resources/xworktech.com/<env>/guance/observability.yaml`，图表与查询定义使用同目录中受版本管理的配置资产。env 内不得使用 `for_each`、`count`、`dynamic` 或 HCL 模板控制循环。

第一批资源、验收与推广顺序见 [实施规划](docs/first-batch-resources-plan.md)。官方 Provider 来源：[GuanceCloud/terraform-provider-guance](https://github.com/GuanceCloud/terraform-provider-guance)。实际实施前需对发布版本的 schema、import 支持、站点配置及免费空间 API 权限完成核验。

管理 API Key、只读 API Key、采集 Token 的 Vault 路径与权限见 [Vault KV 契约](docs/vault-kv-paths.md)。
