# 免费专区与 Provider 能力核验

核验日期：2026-10-12。来源为官方文档与 Provider 发布物；结论只代表文档表述，**未用真实工作空间实测**。

## 来源与事实

| 事实 | 来源 |
| --- | --- |
| 免费版在“免费专区（北京）节点”注册，每用户只能创建 1 个工作空间，最多 5 个成员，工作空间不可解散、Owner 不可移交 | [注册免费版](https://docs.guance.com/plans/free/)（页面更新 2026-09-21） |
| 免费版 **API Key：不支持通过调用 Open API 接口获取和更新工作空间数据** | [版本区分](https://docs.guance.com/plans/differences/) |
| 数据存储 7 天循环；仪表板/笔记/查看器各最多 10 个；监控器最多 10 个且仅支持“阈值检测”；不支持短信通知、数据转发/备份、快照/图表/iframe 分享 | 同上 |
| Terraform Provider 0.1.0（发布于 2026-06-18）的 `region` 取值：`hangzhou`、`ningxia`、`guangzhou`、`vnet`、`hongkong`、`oregon`、`frankfurt`、`singapore`；`end_point` 可自定义；认证为 Workspace API Key，环境变量 `GUANCE_ACCESS_TOKEN`、`GUANCE_END_POINT`、`GUANCE_REGION` | [Registry 文档](https://registry.terraform.io/providers/GuanceCloud/guance/0.1.0/docs)、[Provider README](https://github.com/GuanceCloud/terraform-provider-guance) |

## Provider 0.1.0 源码核验（tag `v0.1.0`，2026-06-16）

阅读 [GuanceCloud/terraform-provider-guance](https://github.com/GuanceCloud/terraform-provider-guance) 的 `v0.1.0` 源码后确认：

| 项 | 源码事实 | 本仓库处理 |
| --- | --- | --- |
| 认证 | 每个请求带 `DF-API-KEY: <access_token>` 头，即工作空间 API Key（OpenAPI） | 管理 Key 经 `GUANCE_ACCESS_TOKEN` 注入 |
| endpoint | `internal/api/client.go`：默认 `https://openapi.guance.com`；`region` 只是查表，`end_point` 非空时覆盖 region。表中有 hangzhou→`openapi.guance.com`、ningxia→`aws-openapi.guance.com`、guangzhou→`cn4-openapi.guance.com`、vnet→`cn5-openapi.guance.com`、hongkong→`cn6-openapi.guance.one`、oregon→`us1-openapi.guance.com`、frankfurt→`eu1-openapi.guance.one`、singapore→`ap1-openapi.guance.one`，**没有免费专区（北京）** | manifest 必须显式给出 `endpoint`，它会覆盖 region；不使用默认杭州 |
| `notify_object.type` | 校验器只接受 12 个值（`dingTalkRobot`…`telegramBot`）；文档完整链路示例里的 `type = "http"` 会被拒绝 | manifest 白名单与源码一致 |
| `notify_object.opt_set` | 创建时存入配置原文；refresh 时用 Go `json.Marshal` 重新编码 API 返回值（键排序、紧凑、`<>&` 转义） | 渲染为 `jsonencode(jsondecode(var.…))`，已实测与 Go 输出逐字节一致，避免二次 plan 出现差异 |
| `dashboard.template_info` | 只在 `template_info_export` 变化时才用导出内容覆盖 state | 远端修改会以 update 形式出现（漂移检测） |
| `mute` | CHANGELOG：OpenAPI 要求 `startTime`/`endTime` 非空 | manifest 强制一次性窗口并要求 start/end |
| `monitor.type` | 只允许 `trigger`、`smartMonitor` | 固定 `trigger` |

仍无法从源码确定：免费空间能否签发可用的 API Key、API 是否在读取时对 webhook/secret 打码（若打码，`opt_set` 会持续出现差异，需要在实测中确认）。

## 对本方案的影响

1. **阻塞性风险**：Provider 通过 OpenAPI 与 API Key 管理资源。官方版本对比写明免费版不支持通过 Open API 获取和更新工作空间数据，因此**免费工作空间很可能无法被 Terraform 管理**。需要用真实工作空间确认：能否创建 API Key、`GET`/`POST` 是否被拒绝。若被拒绝，只能改用商业版/试用工作空间做 UAT，或接受控制台手工管理（失去 IaC 目标）。
2. 免费专区（北京）的 endpoint 不在 Provider README 的 region 列表中，且仓库不假定默认值。真实 endpoint/region 必须来自工作空间，并写入 GitOps `global.endpoint`/`global.region`；不可用杭州等商业站点替代。
3. 配额与首批资源数量兼容：1 个 Dashboard、3 个 Monitor（均为阈值检测 `simpleCheck`）、1 个通知对象、1 个告警策略、1 个静默规则，均低于 10 个的上限；通知类型不得选 `sms`。
4. 7 天循环存储意味着 Monitor 基线只能取最近 7 天内的数据，需在到期前保存基线结论（见 [uat-runbook.md](uat-runbook.md)）。
5. 免费版每用户仅可创建 1 个工作空间：UAT 与 PROD **必须使用不同账号**才能得到独立工作空间，否则只能先不做 PROD（见 [prod-promotion-gate.md](prod-promotion-gate.md)）。

## 需要真实工作空间回答的问题

- [ ] 能否在免费空间创建管理用 API Key？对 Dashboard/通知/告警/Monitor/静默 API 是否返回权限错误？
- [ ] 真实 endpoint 与 region 值；`end_point` 是否需要显式配置。
- [ ] 只读 API Key 的实际权限范围，能否用于 `terraform plan`（只读刷新）。
- [ ] 通知对象类型与告警 `status` 取值（本仓库以文档示例白名单：critical、error、warning、info、ok、nodata、All）。
- [ ] `guance_alert_policy.checker_uuids` 与 `guance_monitor.alert_policy_uuids` 是否为同一关联的两端（本实现只用后者，避免循环依赖和重复管理）。
