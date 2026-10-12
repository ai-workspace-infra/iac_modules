# iac_modules Agent 约束：云资源与 CMDB

四边界完整判定见
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
