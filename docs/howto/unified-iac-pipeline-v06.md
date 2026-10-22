# 统一多云 IaC actions 契约 v0.6

设计来源：knowledge PR #130（已合并）。交付 workflow、runner、审批、正向/销毁 DAG 和最终放行属于 platform-ops-toolkit；本仓库提供 IaC actions、执行脚本与模块。新增内容不包含 delivery workflow。现有 Pipeline Scripts CI 只维护源代码。

环境操作必须使用 GitOps 的 `iac/targets/*.yaml`、固定 GitOps SHA 和固定 IaC SHA。缺声明、缺具体账号、账号/环境冲突、未审查的地址归属、重复 state 或 unsupported 阶段，均在认证和 init 前拒绝。`not_applicable` 只用于明确没有独立 account 对象的 Vultr/Akamai，并提供原因。

## 操作与证据

`iac-targets` 生成目标契约；`iac-bootstrap/account/resources` 使用同一份契约路由认证和生命周期；`iac-receipt` 收尾；`iac-summary` 校验所选全部目标/阶段，`iac-receipt-verify` 供 caller 校验本次运行的 SHA、摘要、manifest、run/attempt 和关联身份。矩阵静态报告也必须匹配当前运行及完整 provider 集合。失败、取消、缺报告、重复或陈旧证据不能返回成功。

资源操作在 runner 私有目录复制固定版本模块后渲染。保留现有 canonical state key 和 CLI `default` workspace，不导入、不迁移 backend、不用 `-target` 模拟阶段拆分。state credential 与 provider credential 分离。Terraform 1.10.5 使用 S3 lockfile 和等待锁；Toolkit 还按 namespace 身份摘要串行化各阶段。

plan 只生成保存的计划及脱敏变更计数，不 apply、不 import、不发布业务 metadata。apply/destroy 校验保存计划摘要并执行同一文件，再用 plan 检查收敛；受保护对象、持久数据卷删除或替换均拒绝。普通 apply 的删除/替换必须另走维护。原始计划、state、日志、tfvars 和凭据只在私有目录，不能上传。生产审批发生在 Toolkit 的受保护 environment；本实现没有跨运行自动批准计划的机制。

销毁逐层使用本次运行的下游清理 receipt。共享/外部依赖、执行身份、backend，以及未声明 `destroy_allowed` 的目标会被阻断。空 state 不作为清理成功。cleanup 结果单独进入 receipt；Vault batch token 不可撤销，以不超过 20 分钟的角色 TTL 约束，并移除所有本地副本；service token 额外 revoke-self。

## Provider 能力与维护

六个认证适配器：`aws-cloud`、`azure-cloud`、`vultr-vps`、`gcp-cloud`、`ucloud`、`akamai-cloud`。实际 API 身份与声明绑定；UAT GCP 还要求禁止访问 PROD 的权限证据。Azure renderer 和尚未拆分的 account state 明确 unsupported；provider registry 或静态通过不能证明运行能力。

GCP identity reconcile 仅在显式 bootstrap/all scope 使用一次性 bootstrap 记录；成功后验证新 WIF、发布固定账号的非敏感 runtime metadata，再删除一次性凭据。bootstrap 计划不自动 adoption。AWS identity recovery 由兼容 wrapper 调用独立 owner；root apply 必须显式 break-glass 且带临时 session token。AWS 三个 identity 地址 adoption 仅在显式 PROD apply maintenance；普通资源操作不会触发维护。

UCloud 的真实 project API 及 firewall/key pair 前置引用需要验证，不能以 key 非空代替。[Firewall API](https://github.com/UCloudDoc-Team/api/blob/master/unet-api/describe_firewall.md) 使用 `FWId`；[Key pair API](https://github.com/UCloudDoc-Team/api/blob/master/uhost-api/describe_uhost_key_pairs.md) 使用 `KeyPairs`，按项目分页查找明确 ID；[Project API](https://github.com/UCloudDoc-Team/api/blob/master/uaccount-api/get_project_list.md) 用于实际账号访问核验。2026-10-07 已核对文档语义，未作真实云验收。

## 验证和上线范围

离线测试覆盖配置、身份、state、plan 保护、前置依赖、保存计划执行、receipt、静态报告以及 action 输入/脚本语法。静态检查不登录 Vault、不访问云 API、不写 state。

P5 仍需要每个启用目标的固定源码、实际 plan/state/身份/清理/inventory 与 caller 验证。GitOps 中现有 Akamai state 仅允许保留已有 state；销毁暂不启用。Serverless target 只核验共享网络和 registry，不重复管理 Cloud Run/Cloudflare 的现有 owner。P6 删除 legacy executor 必须在 UAT 和回退窗口关闭后执行。
