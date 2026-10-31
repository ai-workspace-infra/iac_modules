# iac_modules Agent 约束：云资源与 CMDB

五仓职责完整判定见
[`execution-ownership-migration`](https://github.com/ai-workspace-lab/xworkspace-core-skills/blob/main/skills/engineering-standards/execution-ownership-migration/SKILL.md)。

## 允许内容

Terraform/provider/module/rendering/state 与云资源事实：Vultr、AWS、GCP、Akamai、Ucloud 等 provider 的资源查询/变更，
DNS、Registry、OS Login、临时防火墙、独立块存储和 state；`render/inventory` 产出受控 `cmdb.json` 与 inventory。
输入优先来自 GitOps 声明；CMDB 只记录运行时云事实并交给 Toolkit/Playbooks 消费。

## 硬禁令

- 不执行 SSH、Ansible、Docker、systemd、包安装、Caddy/Xray/Observability/业务服务操作；
- 不执行 PostgreSQL/数据库迁移、备份/恢复、用户/订阅/账本数据操作和服务健康检查；
- 不把人工编辑的 CMDB、运行时 IP 或秘密写回 GitOps；
- 不借 provider renderer 名义承载主机执行逻辑。

Terraform 变更必须说明资源 identity、state、plan 是否含删除/替换；涉及现有主机/独立数据卷必须先提供仅新增/挂载的 plan，发现 delete/replace 立即停止。
更具体的 `terraform-hcl-standard/AGENTS.md` 规则继续适用。

## 声明消费与事实交接

- 环境/provider/account/region、节点逻辑名、资源规格、state namespace 和目标关系来自本次 GitOps 声明及受审查的 state 契约；通用模块和 renderer 不维护第二套环境映射，不按批次/根名称写特殊分支。
- 基础仓库默认由 dispatch 选 `main`，解析出的 commit 是本次运行来源；业务制品版本不得被 IaC 自行改写。
- IaC 是云事实和 CMDB 产出 owner。回执绑定声明 commit/path、provider/account/region、state、实例/卷及附着关系、run ID/attempt/operation 和校验和；不把密钥、token、DSN 写入 CMDB。
- 云防火墙和 Registry 基础设施归本仓；主机内防火墙、Vault 服务/auth 配置、系统账户、K3s 和数据库运行身份归 Playbooks；镜像/Chart 发布归 Artifacts。
- 不因为脚本叫 bootstrap、diagnostic 或 validator 就接入 SSH、主机安装或服务检查。混合脚本应按最终副作用拆分。
- 清理旧 state 前保留资源所有权和恢复证据；删除代码不自动授权删除 state、数据盘、快照或 DNS。历史资源身份和迁移来源声明不得被关键词清理误删。

详细交接与硬编码判定见：[declaration-and-handoff](https://github.com/ai-workspace-lab/xworkspace-core-skills/blob/main/skills/engineering-standards/execution-ownership-migration/references/declaration-and-handoff.md)。
