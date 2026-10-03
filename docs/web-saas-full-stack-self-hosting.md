# Web SaaS Full Stack 自建安装规划

安装入口：`https://install.svc.plus/web-saas/install.sh`

本文先冻结安装边界、模块依赖和部署脚本契约。具体业务代码、Compose 模板和服务配置后续按照本文逐步接入。

状态：设计草案及编排入口；以下域名、v0.1.0 和模块文件是待发布契约，尚未发布或完成真实部署验收。执行部署要求 Linux 和 root 权限；Docker/Compose 或 Kubernetes 工具由宿主机预先准备。IAM 的账号、会话和权限基础由 accounts 提供；OpenPlatform 扩展平台级 IAM/OIDC 集成、Vault 和观测能力。

## 1. 强制 Core Services

以下三个服务是每个自建实例必须安装的基础服务，不能通过模块参数关闭：

| 服务 | 职责 |
| --- | --- |
| `portal` | Web SaaS 控制台、用户入口、产品与模块导航 |
| `accounts` | 账号、IAM 基础接口、会话、权限和账户状态 |
| `postgresql` | PostgreSQL 数据库、扩展、TLS 和备份基础能力 |

任何安装命令都必须自动展开为：

```text
portal accounts postgresql
```

## 2. 可选控制面

| 模块 | 职责 | 依赖 |
| --- | --- | --- |
| `proxy` | Proxy Server 控制面、节点、线路、证书和健康状态 | Core Services |
| `xconnect-zero` | 节点注册、区域入口池、路由策略、客户端配置 | Core Services + `proxy` |
| `open-platform` | 平台级 IAM/OIDC 集成、Vault、监控、日志、指标、审计和平台运维能力 | Core Services |
| `ai-aggregator` | 模型供应商、凭据引用、路由、配额、计费和 API | Core Services + `open-platform` |

依赖关系：

```text
portal + accounts + postgresql       # 永远安装
        ├── proxy
        │   └── xconnect-zero
        ├── open-platform
        │   └── ai-aggregator
        └── proxy + open-platform     # Full Stack 组合
```

## 3. 一键安装命令

### 3.1 只安装 Core Services

```bash
curl -fsSL https://install.svc.plus/web-saas/install.sh | \
  bash -s -- \
  --domain example.com \
  --modules core \
  --release v0.1.0 \
  --yes
```

### 3.2 Core + Proxy

```bash
curl -fsSL https://install.svc.plus/web-saas/install.sh | \
  bash -s -- \
  --domain example.com \
  --modules proxy \
  --release v0.1.0 \
  --yes
```

### 3.3 Core + XConnect Zero

```bash
curl -fsSL https://install.svc.plus/web-saas/install.sh | \
  bash -s -- \
  --domain example.com \
  --modules xconnect-zero \
  --release v0.1.0 \
  --yes
```

### 3.4 完整 Full Stack

```bash
curl -fsSL https://install.svc.plus/web-saas/install.sh | \
  bash -s -- \
  --domain example.com \
  --modules all \
  --mode docker \
  --release v0.1.0 \
  --yes
```

`--modules` 只描述可选模块。无论传入什么值，安装器都必须自动加入三个 Core Services。

## 4. 安装顺序

```text
1. preflight
2. postgresql
3. accounts
4. portal
5. open-platform       # 被请求时
6. proxy               # 被请求时
7. xconnect-zero       # 被请求时
8. ai-aggregator       # 被请求时
9. 全链路健康检查
```

数据库初始化和迁移必须在业务服务启动前完成。模块安装失败时停止后续模块，不自动删除已成功服务。

入口先下载并校验全部选中模块，再开始执行。模块安装器负责幂等部署及本模块健康检查；最终跨模块验收需后续接入。state/modules 和 state/install.env 记录请求计划，不能作为安装成功凭据。

## 5. 域名规划

```text
console.example.com    portal
accounts.example.com   accounts API
db.example.com         PostgreSQL TLS 入口（如启用）
proxy.example.com      Proxy Server 控制面
connect.example.com    XConnect Zero 控制面
vault.example.com      Vault
metrics.example.com    Metrics/Logs/Traces
ai.example.com         AI Aggregator API
```

## 6. Release 契约

安装器从以下目录下载固定版本的模块脚本：

```text
https://install.svc.plus/web-saas/releases/<version>/
├── SHA256SUMS
├── portal.sh
├── accounts.sh
├── postgresql.sh
├── proxy.sh
├── xconnect-zero.sh
├── open-platform.sh
└── ai-aggregator.sh
```

其中 `portal.sh`、`accounts.sh`、`postgresql.sh` 是强制脚本。安装器必须先完成 SHA-256 校验，再执行模块脚本。

当前 SHA256SUMS 与模块来自同一发布源，仅验证传输完整性；发布真实性需要后续接入签名或外部固定摘要。Kubernetes 是预留参数契约，服务适配脚本尚待实现。

每个模块脚本接收统一参数：

```text
--domain <domain>
--mode docker|k8s
--release <version>
--install-root <path>
--yes
```

## 7. 状态目录

```text
/etc/web-saas/
/var/lib/web-saas/releases/<version>/
/var/lib/web-saas/backups/
/var/log/web-saas/
```

入口脚本只负责编排，不保存业务密钥。Vault Token、API Key、数据库密码只能通过运行时环境、Vault bootstrap 或交互式输入注入。

## 8. 安全和验收边界

- 默认不改 DNS、不注册外部账号、不删除持久化数据。
- `reset-data`、卸载和数据库重建必须是独立命令。
- `main`、`latest` 或未校验的远程脚本不能作为生产安装来源。
- 安装成功后仍需验证服务状态、IAM、Vault、数据库、Proxy、XConnect 和 AI API。
- `curl | bash` 只表示安装器已启动，不表示 Full Stack 已运行并完成验收。
