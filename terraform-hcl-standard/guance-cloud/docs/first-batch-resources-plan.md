# Guance 第一批 Terraform 资源规划

## 范围与起点

以 `console-cloudflare-uat.onwalk.net`、Cloudflare Gateway、Cloud Run accounts/content/billing、Supabase xworktech 为首批案例。Terraform 管理 Dashboard、Monitor 和告警配置；主机采集、应用埋点、历史数据迁移和生产路由切换由现有观测与发布链路负责。

现有 `observability.svc.plus/grafana/` 为基线与故障回退入口。目标是可审查、可复制的观测配置，保留自建数据底座。

## 第一批资源清单

| 模块 | Provider 资源 | UAT 首批 | 依赖与验收 |
| --- | --- | --- | --- |
| dashboard | `guance_dashboard` | 1 个 UAT 服务总览 | 请求量、错误率、P95、版本与路由字段可查询；字段与采集端对齐 |
| notify_object | `guance_notify_object` | 1 个测试通知对象 | 使用测试接收方，确认通知成功；地址和凭据按敏感字段处理 |
| alert_policy | `guance_alert_policy` | 1 个 UAT 告警策略 | 引用通知对象的运行时 UUID，验证聚合、恢复通知及通知边界 |
| monitor | `guance_monitor` 或 `guance_monitor_json` | 3 个监控器 | Gateway 错误率、Cloud Run 延迟、黄金 API 可用性；依据真实基线定义阈值 |
| mute | `guance_mute` | 1 个受控发布静默规则 | 限定 UAT、指定资源及有限时间窗，验证自动结束和结束后告警恢复 |

Supabase 延迟监控作为第 4 个候选 Monitor，只有数据库信号可用且口径明确后才加入。Pipeline、角色与成员组留至第二批，避免首次接入同时扩大治理范围。

结构化 monitor 与 JSON monitor 为同一监控器的两种实现选择，不能同时管理同一远端对象。先核验固定版本的覆盖字段，再确定统一实现。

## 声明与生成契约

- GitOps 声明包含环境、站点/endpoint、工作空间标识、资源稳定名称、查询与策略配置、模块间引用；具体字段由 Provider schema 验证后定稿。
- API Key 和通知 webhook secret 从 Vault/CI 注入；不写入 YAML、tfvars、计划文档或日志。已核验 Provider 0.1.0 原生变量 `GUANCE_ACCESS_TOKEN`/`GUANCE_END_POINT`/`GUANCE_REGION`；通知 `opt_set` 经 sensitive 变量注入。
- 每个资源生成独立命名的 resource 块（未抽取 module，原因见 README）；循环仅存在于 Python/Jinja2。
- global 非敏感配置生成 tfvars；逐资源配置展开至 HCL；模块均声明 `required_providers`，source 为 `GuanceCloud/guance`。
- `inventory` 子命令合并 YAML 与 Terraform 输出，生成观测资源 CMDB：资源类型、UUID、环境、名称、所属工作空间。Guance 资源没有主机 IP，不能伪造 Ansible 主机；主机 inventory 仍来自现有基础设施 CMDB。
- UUID 是运行时事实；静态服务名、标签和职责来自 YAML。生成的 HCL、tfvars、CMDB、plan、state 和敏感输出必须忽略。

## UAT / PROD 与 state

UAT 与 PROD 使用独立根目录、state key、凭据及批准流程。优先使用独立工作空间；如果免费专区仅有一个工作空间，首批只部署 UAT，PROD 暂不执行。

state backend 沿用组织统一 S3-compatible 契约；Guance 的账号、workspace 与 namespace 如何映射到现有 key 格式，在实施前确认，不另创冲突的 state 命名规则。免费专区站点是否被 Provider 发布版本支持是上线前置条件，不能默认使用杭州等商业站点替代。已核验：免费专区为北京节点，不在 Provider README 的 region 列表内，且官方版本对比称免费版不支持 Open API，详见 [free-tier-constraints.md](free-tier-constraints.md)。

## 实施顺序

1. 固定已发布 Provider 版本，核验免费专区 API Key、endpoint、权限、资源 schema、import 及读取/更新行为。
2. 盘点已有远端资源；已存在对象先 import，再核对 plan，避免重复创建。
3. 实现共享 renderer 与 5 类模块；以测试数据验证显式块、依赖引用与敏感字段处理。
4. UAT 创建 Dashboard、测试通知对象和告警策略；先在无生产影响的范围验证通知。
5. 加入 3 个 Monitor，模拟失败与恢复，最后验证静默规则的限定范围和到期行为。
6. 第二次 plan 无非预期差异，再进行人工控制台修改后的漂移检测。
7. 保存验收结果与基线后，才创建 PROD 声明并审核独立 plan。

## 验证与回退

实现阶段运行 `terraform fmt`、`terraform validate`、renderer render/inventory 与 CMDB 契约检查（`scripts/offline-check.sh`）。这些是离线检查，不声明远端接入已通过；实测结果见 [acceptance-status.md](acceptance-status.md)。

回退使用先前 GitOps 版本重新 render 和 plan，人工检查后 apply；配置恢复不等于遥测历史数据恢复。对新资源的删除、import 后对象的销毁、通知变更等操作需逐项检查。保留 Grafana 关键告警，只有 Guance 告警验证成功才调整通知主入口。

成功标准：同一 UAT 时间窗指标可解释、3 个告警触发与恢复符合预期、通知无误发、静默自动结束、二次 plan 无非预期差异、关闭 Guance 链路后基础监控仍可用。

## 对季度文章的贡献

第一篇记录免费专区的实际 API/IaC 权限与接入限制；第二篇展示 Grafana 面板意图到 Guance Dashboard/Monitor 的字段映射、plan、import、漂移检测和配置回退。远端 schema、免费空间兼容性和迁移收益均需实测。

来源：[官方 Terraform Provider](https://github.com/GuanceCloud/terraform-provider-guance)、[免费版注册](https://docs.guance.com/plans/free/)、[版本差异](https://docs.guance.com/plans/differences/)。本规划沿用专题既有研究，实施时重新核验发布版本。
