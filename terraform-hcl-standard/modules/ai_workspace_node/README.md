# AI Workspace Node Infrastructure Module

本模块定义了 **AI Workspace (Bridge + QMD + PostgreSQL 17 + 云盘持久存储)** 节点的底层基础设施配置标准。

## 规格基线
- **CPU / 内存**：最低 2 vCPU / 4GB RAM，推荐 4 vCPU / 8GB RAM。
- **持久化磁盘**：独立云盘挂载至 `/var/lib/xworkmate`，满足 pgdata、qmd_models 与 task-archives 存储需求。
- **安全组与防火墙**：
  - 开放端口：TCP `80`、`443`（由 Caddy 自动申请与续期 TLS 证书）、`22`（仅限管理源 IP）。
  - 私有隔离端口：TCP `15432`（PostgreSQL）、`8181`（QMD MCP Server）、`8787`（Bridge 内部端口）严禁直接向公网开放。
