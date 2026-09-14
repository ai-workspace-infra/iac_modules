# XConnect-One Zero Trust Overlay 产品化开发计划

状态：Draft v1
日期：2026-08-27
范围：产品化 CLI、多平台运行时、动态 ACL、控制面投影、Gateway 动态配置、测试与文档体系

## 0. 产品命名

- 产品系列和对外品牌统一为 **XConnect-One**。
- **XConnect-APP** 是五平台客户端、账号入口和安全连接运行时底座；**XConnect-One** 是加载在该底座上的零信任组网产品能力。两者互补组合，不互相替代。
- 终端产品命名为 **XConnect-One Client**，控制面命名为 **XConnect-One Controller**，网关组件命名为 **XConnect-One Gateway Agent**，中继节点命名为 **XConnect-One Relay**。
- CLI 可执行文件、用户命令和稳定技术标识保持小写 `xconnect`；守护进程和服务名可使用 `xconnectd`、`xconnect-gateway-agent`。
- 现有仓库名 `xconnect-app`、`accounts.svc.plus`、`playbooks` 和 `iac_modules` 保持不变，避免仅因品牌命名制造代码迁移。
- 分支、API、配置键和协议标识中的 `xconnect` 保持稳定；面向用户的标题、安装包说明和文档使用 XConnect-One。

## 1. 目标与边界

### 1.1 产品目标

将现有可工作的 WireGuard-over-VLESS、现有 CLI 能力、`accounts.svc.plus` Overlay API、Ansible Gateway 部署和 XConnect-One 多平台客户端收敛为一个产品。现有 `overlayctl` 正式重命名为 `xconnect`，发布物、进程帮助、文档和用户命令均使用 `xconnect`：

```bash
xconnect join <controller-or-invite>
```

加入后，设备自动完成身份注册、密钥生成、地址领取、策略获取、Secure Tunnel 启动、连通性检查和配置签收。用户不需要理解 WireGuard、Xray、VLESS、端口、证书或 Ansible。

### 1.2 首期范围

- L3 Overlay 为默认网络模型。
- Linux、macOS、Windows 提供 GUI 和 CLI。
- iOS、Android 通过 App 登录、邀请链接或二维码执行等价 Join 协议。
- WireGuard 提供端到端加密。
- 现有 VLESS/TLS/XUDP 作为第一版可靠传输。
- 第一版唯一代理内核为 Xray-core：客户端统一通过仓库锁定的 `libXray` 嵌入，Gateway/Relay 使用锁定版本的 Xray-core。
- 第一版不包含 sing-box 依赖、运行时适配器、配置生成器、二进制、服务、fallback 或测试矩阵。
- ACL 默认拒绝，按用户、组、设备、标签、服务和端口授权。
- `accounts.svc.plus` 成为设备、地址、节点、策略和配置版本的唯一事实来源。
- Ansible 只负责 Gateway/Relay 的初始安装和升级，不再维护终端 Peer 静态列表。

### 1.3 非首期范围

- iOS/Android 完整 L2 Ethernet TAP。
- 默认启用 VXLAN、广播或 DHCP 延伸。
- 任意多租户共享 L2 广播域。
- sing-box runtime、adapter、配置兼容层和双内核自动切换。
- 第一版实现完全去中心化的控制面。
- 在 Join 命令中直接运行服务器 Ansible Playbook。

### 1.4 与 XConnect-APP 的组合关系

XConnect-APP 提供可复用的应用外壳和平台能力：登录会话、Flutter 导航、系统安全存储、升级发布、诊断框架，以及每个平台唯一的系统 VPN 入口。XConnect-One 以产品模块接入，提供网络加入、设备身份、Overlay 配置、动态 ACL、WireGuard-over-VLESS 数据面和 Gateway 协同。

组合必须满足以下边界：

- 用户可在同一个 XConnect-APP 中启用 XConnect-One，也可继续使用既有 Secure Tunnel 能力。
- XConnect-One 不复制登录、密钥存储、平台 VPN、更新器和诊断基础设施。
- XConnect-APP 不硬编码 XConnect-One 的控制面 schema、ACL 语义或传输选择。
- CLI 与 GUI 通过相同产品插件调用 shared use case；`xconnect join` 是 XConnect-One 的快捷入口。
- 首期采用编译期内置插件，稳定 ABI/API 后再支持签名的可选插件包；移动端遵循 App Store/Play Store 对动态代码的限制。

## 2. 已有资产和复用决策

| 资产 | 当前能力 | 产品化决策 |
|---|---|---|
| `xconnect-app` | XConnect-APP 的 Flutter、Go core、Apple Packet Tunnel、Android VpnService、Windows/Linux 宿主、五平台构建 | 作为共享客户端底座和插件宿主，内置 XConnect-One 产品模块与 CLI；不新建第二套客户端 |
| `xconnect` CLI（原 `overlayctl`） | login、register-device、sync、render、preflight、up、check、ack、down | 二进制正式重命名为 `xconnect`，并迁入 xconnect-app shared core；`overlayctl` 不再作为产品发布物 |
| `accounts.svc.plus` | Overlay 设备注册、配置下发、ACK、节点 heartbeat 契约 | 作为控制面唯一事实来源；补齐 OpenAPI、ACL、投影和事件流 |
| `xworkmate_bridge_distributed_vpn` | 双向 WireGuard-over-VLESS/XUDP、Vault、Gateway heartbeat、Peer 验证 | 作为 Gateway 数据面基线，泛化命名并改为动态配置 agent |
| `vpn-overlay/wireguard` | 通用 Hub/Site WireGuard | 保留为普通 UDP 和站点网络部署能力 |
| `vpn-overlay/vxlan` | Linux VXLAN over WG | 后续作为 Linux L2 Gateway 后端，不进入移动端 |
| `setup-dnat` | 网络和服务映射 | 后续映射成受 ACL 管理的 route/service publish |
| `xray-exporter`、Alloy | Xray 和系统日志观测 | 统一为 XConnect-One transport/runtime 指标 |
| closure scripts | 可重放的端到端闭环与证据目录 | 升级为 CI/E2E 的正式验收框架 |

## 3. 目标系统架构

```text
┌──────────────────────────────┐   HTTPS / mTLS   ┌────────────────────────┐
│ XConnect-APP Host            │─────────────────▶│ accounts.svc.plus      │
│ Account / UI / Secret Store  │ config/events/ack│ Overlay Control Plane  │
│ ┌──────────────────────────┐ │                  └────────────┬───────────┘
│ │ XConnect-One Plugin      │ │                               │ signed snapshot
│ │ CLI / Flutter routes     │ │                               ▼
│ │ shared usecase/providers │ │                  ┌────────────────────────┐
│ └──────────────────────────┘ │                  │ xconnect-gateway-agent │
│ System Tunnel Runtime SPI    │── WG/VLESS/XUDP ─▶│ provider/backends      │
└──────────────────────────────┘                  └────────────┬───────────┘
                                                              ▼
                                                      Private services/LAN
```

### 3.1 控制面职责

- 用户、组织、网络和成员身份。
- 一次性邀请和设备注册。
- 设备公钥、状态、撤销和密钥版本。
- Overlay 地址租约。
- Gateway/Relay 节点健康、区域和传输能力。
- ACL 源策略、编译版本和审计。
- 客户端配置与 Gateway 投影。
- 配置版本、ETag、ACK 和回滚。

控制面不得保存客户端 WireGuard 私钥，不得解密业务数据。

### 3.2 客户端职责

- 本地生成并安全保存设备私钥。
- 执行 Join/Leave 和设备认证。
- 获取并验证签名配置。
- 通过平台 Runtime SPI 应用网络、路由和策略。
- 启停 WireGuard/Xray 数据面。
- 汇报健康状态、能力、配置版本和诊断摘要。

### 3.3 Gateway Agent 职责

- 向控制面注册/心跳并声明能力。
- 获取签名 Gateway snapshot。
- 原子更新 WireGuard peers：优先 `wg syncconf`，避免重启接口。
- 原子更新动态 ACL：Linux 首期使用 nftables set/map。
- 保留 last-known-good 配置并在失败时回滚。
- 上报 apply result、当前 generation 和数据面健康。

### 3.4 Ansible 职责

- 安装 WireGuard、Xray、`xconnect-gateway-agent` 和 systemd unit。
- 配置节点身份、Vault 访问、证书路径和 bootstrap token。
- 配置内核参数、日志、监控和包版本。
- 验证 Gateway 可连接控制面并成功应用第一份 snapshot。

Ansible 不再渲染动态客户端 Peer，不再因用户 Join 而重跑。

### 3.5 产品插件架构

XConnect-APP 通过稳定的 Product Plugin API 组合 XConnect-One。首期插件随应用编译和签名，不加载任意第三方动态代码，但接口按可扩展能力设计：

```go
type ProductPlugin interface {
    Manifest() ProductManifest
    Register(HostServices) error
    Commands() []CommandSpec
    Profiles() []ProfileProvider
    Health(context.Context) PluginHealth
}
```

`HostServices` 只暴露最小能力：账号会话、Secret Store、系统 Tunnel Runtime、受控网络请求、事件总线、日志/指标和 UI route registration。插件不能直接持有平台 root 权限或另起第二个系统 VPN 入口。

扩展点分为：

- `ControlPlaneProvider`：注册、配置同步、事件和 ACK。
- `TransportProvider`：第一版仅注册由 Xray-core/libXray 驱动的 VLESS/TLS/XUDP；其他实现不进入 v1。
- `PolicyProvider`：策略验证、解释和本地快速拒绝；Gateway 仍是强制执行点。
- `ProfileProvider`：把产品配置编译为平台无关 Tunnel Profile。
- `DiagnosticsContributor`：向统一诊断包添加已脱敏证据。
- `GatewayProvider`：把控制面 snapshot 对接到 WireGuard、ACL 和 Relay 后端。

插件 manifest 至少包含 plugin ID、语义版本、host API 范围、所需 capability、配置 schema 版本和签名信息。Host 必须在激活前完成兼容性、来源、权限和 schema 校验；插件失败不得破坏其他 XConnect-APP 连接模式。

## 4. 仓库设计

不建议增加新的顶层产品仓库。使用三个现有仓库，契约由控制面 OpenAPI 生成客户端代码。

### 4.1 `xconnect-app`

```text
xconnect-app/
├── cmd/
│   └── xconnect/                 # Go CLI：join/up/down/status/diagnose
├── product/
│   ├── sdk/                      # Product Plugin API、manifest、HostServices
│   └── xconnect_one/             # XConnect-One 内置产品插件
├── overlay/
│   ├── api/                      # OpenAPI 生成的 Go client
│   ├── auth/                     # 登录、device code、token refresh
│   ├── enroll/                   # 设备密钥、注册、撤销
│   ├── config/                   # 配置模型、签名验证、版本存储
│   ├── policy/                   # 客户端策略模型与校验
│   ├── runtime/                  # 平台无关 Runtime SPI
│   ├── transport/                # WG-over-VLESS 配置和状态
│   ├── diagnostics/              # 诊断与脱敏 evidence
│   └── testkit/                  # fake controller/runtime/clock
├── go_core/                      # 现有 Go/Xray 核心和 FFI
├── lib/                          # 现有 Flutter UI；调用 overlay service
├── ios/ macos/ android/ windows/ linux/
├── test/                         # Dart 单元/Widget 测试
├── integration_test/             # Flutter 平台集成测试
├── e2e/                          # CLI、虚拟网络、真实设备场景
├── api/generated/                # 生成的 Dart models/client
└── docs/
```

Go package module 边界：

```text
cmd/xconnect
  → overlay/usecase
      → overlay/controlplane
      → overlay/runtime
      → overlay/state

Flutter
  → OverlayService
      → Pigeon/FFI
          → 相同 overlay/usecase
```

CLI 和 GUI 必须调用相同 use case，不能各自实现一套 Join 状态机。

### 4.2 `accounts.svc.plus`

```text
accounts.svc.plus/
├── api/
│   └── openapi/
│       └── overlay-v1.yaml       # Overlay API 单一契约源
├── cmd/
│   ├── accountsvc/
│   └── overlay-adminctl/         # 仅内部控制面运维；不得作为终端产品 CLI
├── internal/overlay/
│   ├── domain/                   # Network/Device/Node/Policy/Lease
│   ├── service/                  # Enroll/Config/Policy/Projection
│   ├── compiler/                 # ACL 编译器
│   ├── projection/               # client/gateway snapshot
│   ├── repository/               # DB store
│   ├── handler/                  # HTTP/SSE handlers
│   ├── signing/                  # snapshot 签名
│   └── audit/
├── sql/migrations/
├── tests/
│   ├── contract/
│   ├── integration/
│   └── fixtures/
└── docs/overlay/
```

### 4.3 `ai-workspace-infra`

```text
playbooks/
├── roles/vhosts/xconnect-gateway/
│   ├── defaults/
│   ├── handlers/
│   ├── tasks/
│   ├── templates/
│   │   ├── gateway-agent.yaml.j2
│   │   ├── xconnect-gateway-agent.service.j2
│   │   ├── xray-wg-transport.service.j2
│   │   └── wg-bootstrap.conf.j2
│   └── tests/                    # Molecule scenarios
├── xconnect-gateway.yml
└── scripts/verify-xconnect-closure.sh

iac_modules/vpn-overlay/
├── README.md
├── PRODUCTIZATION_DEVELOPMENT_PLAN.md
├── schemas/                      # infra 消费的 snapshot JSON Schema
├── examples/
└── legacy/                       # 旧 shell 示例
```

## 5. CLI 产品设计

### 5.0 二进制命名

- 唯一面向用户的 CLI 二进制：`xconnect`。
- Go 入口：`xconnect-app/cmd/xconnect`。
- 安装目标：Linux/macOS `/usr/local/bin/xconnect`，Windows `xconnect.exe`。
- 包名和发布物使用 `xconnect`，例如 `xconnect-linux-amd64`、`xconnect-darwin-arm64`、`xconnect-windows-amd64.exe`。
- Shell completion、man page、system service IPC client 和文档示例全部使用 `xconnect`。
- `overlayctl` 只被视为重命名前的历史名称，不再生成或发布同名兼容二进制，避免长期维护两套入口。
- 迁移前的闭环脚本完成切换后，将变量 `OVERLAYCTL_BIN` 改为 `XCONNECT_BIN`，构建路径从 `cmd/overlayctl` 改为 `cmd/xconnect`。

### 5.1 命令面

```bash
xconnect join <invite-url-or-controller> [--network NAME] [--device-name NAME]
xconnect up [NETWORK]
xconnect down [NETWORK]
xconnect status [--json]
xconnect peers [--json]
xconnect ping <device-or-ip>
xconnect routes
xconnect policy explain <destination> [--port N] [--protocol tcp]
xconnect config sync
xconnect diagnose [--output FILE]
xconnect leave [--revoke-device]
xconnect version
```

管理员/网关命令独立命名空间：

```bash
xconnect admin invite create --network prod --expires 15m --uses 1
xconnect admin policy validate policy.yaml
xconnect admin policy publish policy.yaml
xconnect gateway status
xconnect gateway snapshot inspect
```

### 5.2 `join` 状态机

```text
INIT
 → DISCOVER_CONTROLLER
 → AUTHENTICATE_USER
 → GENERATE_DEVICE_KEYS
 → REGISTER_DEVICE
 → WAIT_FOR_APPROVAL（按网络策略可选）
 → FETCH_SIGNED_CONFIG
 → VALIDATE_CONFIG
 → APPLY_PLATFORM_PROFILE
 → START_DATA_PLANE
 → CONNECTIVITY_CHECK
 → ACK_CONFIG
 → JOINED
```

要求：

- 每一步可重入，进程中断后可恢复。
- 一次性 Join token 不写日志，不写 shell history 建议值。
- 私钥在客户端生成，注册 API 只发送公钥。
- 配置验证失败不能破坏正在工作的 last-known-good。
- `--json` 输出稳定的机器接口；普通输出面向用户。
- 错误包含稳定 code、阶段、可操作建议和 correlation ID。

### 5.3 本地状态模板

```json
{
  "schema_version": 1,
  "controller": "https://accounts.svc.plus",
  "device_id": "dev_01...",
  "network_id": "xworkmate-private",
  "config_generation": 42,
  "config_etag": "sha256:...",
  "runtime": {
    "state": "connected",
    "proxy_core": "xray",
    "platform_adapter": "darwin-packet-tunnel",
    "active_transport": "vless-tls-xudp"
  }
}
```

SignedConfig、GatewaySnapshot、manifest 和本地状态中的 `proxy_core` 在 v1 必须使用闭集枚举 `xray`，不能接受自由字符串后再尝试其他运行时。

私钥和 refresh token 必须存系统安全存储：Apple Keychain、Android Keystore、Windows Credential Manager/DPAPI、Linux Secret Service；没有安全存储时使用 root-only 文件并明确降级状态。

## 6. 多平台 Runtime SPI

这里的 Runtime SPI 只抽象系统 VPN 生命周期、权限、路由和平台桥接，不表示第一版支持多个代理内核。v1 的唯一 core ID 为 `xray`：客户端实现绑定 `libXray/xray-core`，Gateway/Relay 实现绑定 Xray-core。任何 `sing-box` core ID、依赖或配置均视为不支持并在校验阶段拒绝。

### 6.1 平台无关接口

```go
type Runtime interface {
    Capabilities(ctx context.Context) (Capabilities, error)
    Validate(ctx context.Context, cfg SignedConfig) (ValidationReport, error)
    Prepare(ctx context.Context, cfg SignedConfig) (PreparedConfig, error)
    Apply(ctx context.Context, cfg PreparedConfig) (ApplyResult, error)
    Start(ctx context.Context, networkID string) error
    Stop(ctx context.Context, networkID string) error
    Status(ctx context.Context, networkID string) (Status, error)
    Diagnostics(ctx context.Context, networkID string) (DiagnosticBundle, error)
    Rollback(ctx context.Context, generation uint64) error
}
```

`Capabilities` 至少包含：

```json
{
  "l3": true,
  "l2_gateway": false,
  "wireguard_backend": "userspace",
  "system_tunnel": "network-extension",
  "proxy_core": "xray",
  "transports": ["vless-tls-xudp"],
  "ipv6": true,
  "policy_enforcement": "packet-filter"
}
```

### 6.2 平台映射

| 平台 | 系统入口 | Runtime 实现 | 首期支持 |
|---|---|---|---|
| macOS | `NEPacketTunnelProvider` | Swift Host + `libXray` | L3、配置、状态、诊断 |
| iOS | `NEPacketTunnelProvider` | Swift Packet Tunnel + static `libxray.a` | L3、邀请链接/二维码、移动网络切换 |
| Android | `VpnService` | Kotlin service + `libXray`/JNI | L3、Always-on 兼容 |
| Windows | Windows Service + Wintun/WireGuard backend | Go service + `libXray` helper | L3、开机启动、升级回滚 |
| Linux | systemd + kernel WG，必要时 userspace | Go daemon + `libXray`/netlink/polkit | L3、route gateway、后续 L2 |

Apple 平台必须继续使用现有 Packet Tunnel，不引入 sudo 路由修改或第二种系统网络入口。

### 6.3 运行时进程模型

- Linux/Windows：`xconnect` CLI 通过本地受保护 IPC 调用 `xconnectd`。
- macOS：Flutter/CLI 通过宿主调用 Network Extension；敏感网络操作由 extension 执行。
- iOS/Android：GUI 是唯一用户入口，复用 Join use case；不要求 shell CLI。
- IPC 必须验证本地调用者身份和请求权限。

## 7. 控制面数据模型

建议表/聚合：

| 实体 | 关键字段 |
|---|---|
| `overlay_networks` | id、tenant_id、name、address_pool_v4/v6、policy_version |
| `overlay_memberships` | network_id、subject_type、subject_id、role、state |
| `overlay_devices` | id、user_id、name、platform、public_key、tags、state、last_seen |
| `overlay_address_leases` | network_id、device_id、address、state、leased_at、released_at |
| `overlay_nodes` | id、network_id、role、region、wg_public_key/address、transport、health |
| `overlay_node_capabilities` | node_id、capability、value、observed_at |
| `overlay_routes` | network_id、prefix、advertiser_device/node、approval、metric |
| `overlay_services` | owner、protocol、port/range、tags、route target |
| `overlay_acl_policies` | network_id、source_document、revision、state、author |
| `overlay_policy_builds` | policy_id、compiler_version、artifact、hash、result |
| `overlay_config_generations` | network_id、generation、policy_hash、created_at |
| `overlay_device_configs` | device_id、generation、signed_payload、ack_state |
| `overlay_node_snapshots` | node_id、generation、signed_payload、apply_state |
| `overlay_join_tokens` | hash、network_id、constraints、expires_at、remaining_uses |
| `overlay_audit_events` | actor、action、target、before/after hash、correlation_id |

约束：

- 同一网络内地址唯一。
- 活跃设备公钥唯一。
- Join token 只保存不可逆 hash。
- 配置 generation 单调递增。
- 撤销和地址回收必须可审计。
- 删除设备先 tombstone，再异步回收地址，避免旧配置短时复活。

## 8. 动态 ACL 设计

### 8.1 策略格式

```yaml
apiVersion: overlay.xconnect.svc.plus/v1alpha1
kind: NetworkPolicy
metadata:
  name: xworkmate-private-default
spec:
  defaultAction: deny
  groups:
    developers:
      users:
        - alice@example.com
  tagOwners:
    tag:gateway:
      - group:platform-admins
  rules:
    - id: dev-to-bridge-api
      action: accept
      sources:
        - group:developers
      destinations:
        - tag:xworkmate-bridge
      protocols: [tcp]
      ports: [8787]
    - id: device-health
      action: accept
      sources: [tag:monitor]
      destinations: [tag:gateway]
      protocols: [tcp]
      ports: [9100]
```

### 8.2 编译流程

```text
Policy source
 → schema validation
 → subject/tag resolution
 → address/service expansion
 → conflict and shadow analysis
 → canonical IR
 → client projection + gateway projection
 → deterministic hash
 → sign
 → generation publish
```

编译器必须是确定性的：同一输入、同一 compiler version 必须得到相同 artifact hash。

### 8.3 执行位置

- Gateway 是第一版强制执行点，防止恶意客户端绕过本地策略。
- 客户端同时执行出站策略，用于快速拒绝和清晰错误提示，但不能作为唯一防线。
- Linux Gateway 使用 nftables atomic ruleset/set swap。
- Apple/Android 客户端在 Packet Tunnel 数据路径应用 compiled rules。
- Windows 使用 WFP 或 daemon 数据路径过滤；Linux 客户端使用 nftables/eBPF，按实现成熟度选择。

### 8.4 策略行为

- 默认拒绝。
- 明确 deny 优先于 accept。
- 管理控制面流量单独定义，不被业务 ACL 意外切断。
- 路由发布、exit node、L2 Segment 加入需要独立授权。
- 策略更新失败保留上一 generation，并上报失败原因。
- `xconnect policy explain` 返回匹配 rule ID、主体解析和最终动作。

## 9. 控制面 API 契约

首批 OpenAPI 接口：

```text
POST   /api/overlay/v1/join-tokens/exchange
POST   /api/overlay/v1/devices
GET    /api/overlay/v1/devices/{id}
POST   /api/overlay/v1/devices/{id}/rotate-key
POST   /api/overlay/v1/devices/{id}/revoke
GET    /api/overlay/v1/config
POST   /api/overlay/v1/config/{generation}/ack
GET    /api/overlay/v1/events

POST   /api/internal/overlay/v1/nodes/heartbeat
GET    /api/internal/overlay/v1/nodes/{id}/snapshot
POST   /api/internal/overlay/v1/nodes/{id}/apply-result

POST   /api/overlay/v1/policies/validate
POST   /api/overlay/v1/policies
GET    /api/overlay/v1/policies/{revision}
POST   /api/overlay/v1/policies/{revision}/activate
```

配置响应模板：

```json
{
  "schema_version": 1,
  "generation": 42,
  "issued_at": "2026-08-27T10:00:00Z",
  "expires_at": "2026-08-28T10:00:00Z",
  "network": {
    "id": "xworkmate-private",
    "address": "172.29.10.10/32",
    "dns": []
  },
  "wireguard": {
    "peers": [
      {
        "node_id": "xworkmate-bridge",
        "public_key": "...",
        "allowed_ips": ["172.29.10.0/24"],
        "endpoint": "127.0.0.1:51830"
      }
    ]
  },
  "transport": {
    "type": "vless-tls-xudp",
    "host": "xworkmate-bridge.svc.plus",
    "port": 2443,
    "credential_ref": "sealed:..."
  },
  "policy": {
    "revision": 7,
    "artifact_hash": "sha256:...",
    "rules": []
  },
  "signature": {
    "key_id": "overlay-config-2026-01",
    "algorithm": "Ed25519",
    "value": "..."
  }
}
```

敏感传输凭据不能作为所有租户共享的永久 UUID。迁移期兼容共享 UUID，目标是按设备或短期授权生成可撤销凭据。

## 10. 用控制面投影替换静态 `group_vars`

### 10.1 当前问题

当前 `xworkmate_bridge_distributed_vpn_clients` 静态包含：

- device id
- WireGuard IP
- public key
- attach_to Gateway

每次加入/撤销客户端都需要修改 inventory 并重跑 Ansible，无法形成即时 Join 和零信任撤销。

### 10.2 目标投影

控制面为每个 Gateway 生成 snapshot：

```json
{
  "node_id": "xworkmate-bridge",
  "generation": 105,
  "peers": [
    {
      "device_id": "shenlan-macos",
      "public_key": "...",
      "allowed_ips": ["172.29.10.10/32"]
    }
  ],
  "forwarded_routes": [
    {
      "prefix": "172.29.10.11/32",
      "via_peer_node": "cn-xworkmate-bridge"
    }
  ],
  "policy_artifact": {},
  "signature": {}
}
```

### 10.3 迁移阶段

#### M0：冻结并记录基线

- 导出现有静态客户端列表、WG peer、AllowedIPs 和 handshake。
- 给现有配置生成 baseline hash。
- closure 脚本保存迁移前 evidence。

#### M1：静态列表导入控制面

- 编写一次性 importer，将 `group_vars` 客户端转换为 device/lease/attachment。
- dry-run 输出 diff，默认不写数据库。
- 导入后生成的 Gateway snapshot 必须与 Jinja 模板输出语义一致。

#### M2：双写和影子投影

- Ansible 仍应用静态列表。
- Gateway agent 只拉取 snapshot、校验签名并生成候选 `wg syncconf`，不应用。
- CI 比较 static 与 projected peer/route 集合。

#### M3：动态应用，静态兜底

- Gateway agent 成为动态 Peer 应用者。
- Ansible 只写 Gateway 自身、节点间 Peer 和 last-known-good bootstrap。
- 出现控制面故障时保持现有 Peer，不清空接口。

#### M4：停止静态客户端投影

- 删除 `xworkmate_bridge_distributed_vpn_clients` 的运行时依赖。
- inventory 只保留 Gateway 节点定义。
- 静态字段存在时 CI 报错，迁移工具保留一个发布周期。

#### M5：删除兼容代码

- 移除旧 Jinja 客户端循环。
- 原 `overlayctl apply-playbooks-client` 能力退出产品路径；`xconnect` 不提供让普通终端运行服务器 Playbook 的命令。
- 文档全部切换到 `xconnect join`。

### 10.4 一致性与故障策略

- snapshot 采用完整期望状态，不采用不可重放的增量命令。
- 每份 snapshot 有 generation、hash、签名和过期时间。
- Gateway 只接受更高 generation，除非执行显式回滚。
- API 不可达时保留 last-known-good，不能把 peer 清空。
- 撤销事件走快速 events 通道，定期完整同步负责最终一致性。
- `wg syncconf` 后读取 `wg show` 校验实际状态，再 ACK。

## 11. 测试策略与 Cases

### 11.1 测试层次

| 层次 | 工具/环境 | 目标 |
|---|---|---|
| 单元测试 | Go test、Flutter test、平台单测 | 状态机、编译器、渲染、错误处理 |
| Contract | OpenAPI validator、JSON Schema、golden | 客户端/控制面/Gateway 契约稳定性 |
| 集成测试 | PostgreSQL、fake Vault、fake controller | API、租约、ACK、投影、并发 |
| 网络测试 | Linux network namespace、Docker、tc/netem | WG/VLESS、路由、ACL、丢包和恢复 |
| 平台测试 | macOS/iOS/Android/Windows/Linux runner | 系统 VPN 生命周期和权限 |
| E2E | 两个 Gateway + 真实控制面 staging | `join` 到私网服务的完整闭环 |
| 安全测试 | gosec、gitleaks、fuzz、DAST | 密钥、鉴权、输入和策略绕过 |
| 稳定性 | soak、网络切换、进程重启 | 长连接、内存、恢复和配置更新 |

### 11.2 CLI Join Cases

| ID | 场景 | 预期 |
|---|---|---|
| JOIN-001 | 有效一次性 token 首次 Join | 注册、启动、连通性、ACK 全成功 |
| JOIN-002 | token 已使用 | 稳定错误码 `JOIN_TOKEN_USED`，不生成残留设备 |
| JOIN-003 | token 过期 | `JOIN_TOKEN_EXPIRED`，不改变本地现有连接 |
| JOIN-004 | Join 中途进程退出 | 再次执行从安全 checkpoint 恢复 |
| JOIN-005 | 同一设备重复 Join | 幂等返回现有设备或执行显式 re-enroll |
| JOIN-006 | 设备需管理员审批 | 显示 pending，不忙轮询，不启动数据面 |
| JOIN-007 | 控制面返回错误签名 | 拒绝应用并保留 last-known-good |
| JOIN-008 | 地址池耗尽 | 明确错误和 correlation ID，不产生半注册状态 |
| JOIN-009 | 本地安全存储不可用 | 按平台策略失败或明确降级，不静默明文保存 |
| JOIN-010 | 启动成功但私网探测失败 | 不 ACK connected，输出分层诊断 |

### 11.3 配置与迁移 Cases

| ID | 场景 | 预期 |
|---|---|---|
| CFG-001 | 新 generation 正常应用 | 原子切换并 ACK generation |
| CFG-002 | 相同 generation 重放 | 幂等无变更 |
| CFG-003 | 低 generation 到达 | 拒绝降级 |
| CFG-004 | 显式授权回滚 | 回到目标 generation 并审计 |
| CFG-005 | Apply 中途失败 | 自动恢复 last-known-good |
| CFG-006 | 控制面离线 | 保持现有连接，标记 stale |
| CFG-007 | 静态与动态投影一致 | Peer、AllowedIPs、路由语义 diff 为空 |
| CFG-008 | 单接入客户端跨 Gateway 返回 | 对端节点包含正确 forwarded `/32` |
| CFG-009 | 客户端撤销 | SLA 内从所有相关 Gateway 移除且新握手失败 |
| CFG-010 | 两个设备并发领取地址 | 地址唯一，无重复租约 |

### 11.4 ACL Cases

| ID | 场景 | 预期 |
|---|---|---|
| ACL-001 | 无规则访问 | 默认拒绝 |
| ACL-002 | 组到标签指定端口 | 仅授权端口允许 |
| ACL-003 | 同时命中 accept 和 deny | deny 优先 |
| ACL-004 | 标签 owner 非法赋值 | 控制面拒绝设备标签变更 |
| ACL-005 | 用户被移出组 | 新 policy generation 后访问失效 |
| ACL-006 | 客户端禁用本地策略 | Gateway 仍然阻止访问 |
| ACL-007 | 策略包含未知主体 | validate 失败，不发布 |
| ACL-008 | 策略规则被完全遮蔽 | compiler warning，管理员可查看原因 |
| ACL-009 | 管理流量保护 | 业务策略不会切断 control-plane keepalive |
| ACL-010 | `policy explain` | 返回最终动作和匹配 rule ID |
| ACL-011 | 大规模策略 | 10k 设备/1k 规则在目标时间内编译和应用 |
| ACL-012 | IPv6 | 与 IPv4 等价执行，无绕过路径 |

### 11.5 传输和网络 Cases

| ID | 场景 | 预期 |
|---|---|---|
| NET-001 | 正常 VLESS/TLS/XUDP | WG handshake 和双向业务流量成功 |
| NET-002 | Xray 先启动/WG 后启动 | 自动恢复，无需手工重启 |
| NET-003 | WG 先启动/Xray 后启动 | Keepalive 后恢复握手 |
| NET-004 | 1%/5% 丢包 | 连接不崩溃，指标反映质量下降 |
| NET-005 | 200ms RTT | 无错误断线，吞吐达到定义门槛 |
| NET-006 | Gateway Xray 重启 | 客户端自动重连 |
| NET-007 | TLS 证书过期/主机名错误 | 明确失败且不允许 insecure fallback |
| NET-008 | 错误 VLESS credential | 鉴权失败，不泄露服务信息 |
| NET-009 | MTU 边界 | 大包不黑洞，诊断能发现 MTU 问题 |
| NET-010 | 双 Gateway 切换 | 配置和路由保持一致，无地址冲突 |
| NET-011 | 配置声明 `proxy_core != xray` | 客户端和 Gateway 在启动前拒绝，不做其他内核 fallback |

### 11.6 平台 Cases

- Apple：Profile 保存、授权拒绝、Packet Tunnel 启停、App 重启、系统重启、Wi-Fi/蜂窝切换、睡眠唤醒、后台内存 soak。
- Android：VpnService 授权、Always-on、应用被杀、Doze、Wi-Fi/蜂窝切换、fd 泄漏。
- Windows：Service 安装/升级/卸载、Wintun 缺失、UAC、重启恢复、多用户会话。
- Linux：systemd、polkit、kernel WG 缺失、nftables rollback、NetworkManager 共存。
- 所有平台：Join、撤销、配置轮换、过期配置、日志脱敏和诊断包。

### 11.7 插件组合 Cases

| ID | 场景 | 预期 |
|---|---|---|
| PLUG-001 | XConnect-One manifest 与 Host API 兼容 | 注册成功，CLI/UI route 和 profile 可发现 |
| PLUG-002 | 插件要求不支持的 capability | 激活前拒绝并返回稳定错误，不影响既有连接 |
| PLUG-003 | 插件签名或来源无效 | 拒绝加载且写入脱敏审计事件 |
| PLUG-004 | XConnect-One 初始化或运行失败 | 故障隔离，XConnect-APP 其他连接模式仍可使用 |
| PLUG-005 | CLI 与 GUI 调用同一产品插件 | 同一 fixture 产生相同状态、配置和 ACK |
| PLUG-006 | 两个产品请求系统 VPN 入口 | Host 仲裁并保持单一入口，不产生路由竞争 |
| PLUG-007 | 注册 sing-box 或未知代理内核 | v1 Host 拒绝注册，构建产物不包含对应依赖和二进制 |
| PLUG-008 | 插件升级与回滚 | manifest/schema 迁移可回滚，last-known-good 可恢复 |

### 11.8 测试 Case 模板

```markdown
## CASE-ID 标题

- Level: unit | integration | e2e | platform | security | soak
- Platforms: linux, macos, windows, ios, android
- Preconditions:
- Fixture/Topology:
- Steps:
- Expected result:
- Required evidence:
- Cleanup:
- Automation owner:
- Release gate: required | optional
```

## 12. CI/CD 与发布门禁

### 12.0 分支与分批编码策略

- 本计划文档使用独立文档分支并提交到 `main` 的文档 PR。
- 产品化编码使用长期特性分支 `codex/xconnect-overlay-productization`，不直接提交到 `main`。
- 每个 Phase 再按可独立验证的 Batch 建立短期分支，例如：

```text
codex/xconnect-overlay-productization
├── codex/xconnect-batch-01-contracts
├── codex/xconnect-batch-02-cli-join
├── codex/xconnect-batch-03-gateway-shadow
├── codex/xconnect-batch-04-dynamic-peers
├── codex/xconnect-batch-05-acl-compiler
└── codex/xconnect-batch-06-platform-closure
```

- Batch 分支只合入产品化特性分支；未经明确指令，不向 `main` 创建编码 PR。
- 每个 Batch 必须有明确输入、输出、测试 Case、evidence 和 rollback 点，验证通过后才开始下一 Batch。
- 特性分支持续同步 `main`，但禁止用破坏性 reset 清理用户或其他分支的工作。
- 文档、OpenAPI、schema、golden 和测试可以随 Batch 一起演进，但每个 Batch 结束时必须保持特性分支可构建、可测试、可恢复。
- 最终是否拆分为多个 `main` PR 或使用一个汇总 PR，在 GA 前由维护者明确决定。

### 12.1 Pull Request 门禁

- Go format、vet、test、race（支持的平台）。
- Flutter format、analyze、test。
- OpenAPI lint 和生成代码无 diff。
- SQL migration forward 测试。
- ACL compiler golden + fuzz smoke。
- JSON Schema contract tests。
- Ansible lint、syntax-check、Molecule。
- gitleaks、依赖漏洞和许可证检查。
- Linux namespace 基础 E2E：两个 client、两个 Gateway、ACL allow/deny。

### 12.2 Nightly

- 五平台构建矩阵。
- Android emulator tunnel smoke。
- Windows VM service/tunnel smoke。
- macOS Packet Tunnel smoke。
- Linux netem 故障注入。
- 控制面/Gateway 断连和配置回滚。
- 24 小时短 soak。

### 12.3 Release Candidate

- iOS 真机 Packet Tunnel smoke 和 soak。
- macOS arm64/x64 签名、公证、升级。
- Windows MSI/MSIX 安装、升级、卸载。
- Linux DEB/RPM 安装升级。
- Android APK/AAB 真机网络切换。
- Staging 完整 `join → policy → revoke`。
- closure evidence checker 必须返回 `closure_ready=1`。

### 12.4 版本策略

- OpenAPI 和配置 schema 使用显式 `v1`，新增字段向后兼容。
- 客户端、Gateway Agent、控制面各自 SemVer。
- snapshot 包含 `min_client_version` 和 `min_gateway_version`。
- 至少支持当前和上一个客户端 minor 版本。
- 数据库 migration 只能前向兼容一个发布窗口，回滚依赖 feature flag 和旧列保留。

## 13. 可观测性和 SLO

关键指标：

```text
xconnect_join_total{result,stage}
xconnect_config_apply_total{result,generation}
xconnect_config_staleness_seconds
xconnect_device_online
xconnect_gateway_snapshot_generation
xconnect_gateway_snapshot_apply_seconds
xconnect_wireguard_latest_handshake_seconds
xconnect_wireguard_rx_bytes_total
xconnect_wireguard_tx_bytes_total
xconnect_transport_sessions{type,state}
xconnect_policy_compile_seconds
xconnect_policy_denied_total{rule_id}
```

建议初始 SLO：

- 已认证用户 Join 成功率 ≥ 99%。
- 正常网络下 Join P95 ≤ 20 秒。
- 配置发布到 Gateway 应用 P95 ≤ 10 秒。
- 紧急设备撤销 P95 ≤ 15 秒。
- 配置应用失败时 last-known-good 恢复 ≤ 5 秒。
- Gateway 控制面不可用时现有数据面不受影响。

日志必须包含 correlation ID、device/node ID 的不可逆或非敏感标识、generation 和阶段；不得记录私钥、完整 token、VLESS credential 或用户密码。

## 14. 安全开发要求

- Join token 一次性、短期、服务端只存 hash。
- 客户端和 Gateway snapshot 使用 Ed25519 签名。
- Gateway Agent 使用独立节点身份和短期凭据，不能使用全局 root token。
- Vault token 不进入 inventory、命令行或日志。
- WireGuard 私钥只存在对应设备/Gateway。
- VLESS 共享 UUID 作为兼容债务登记，逐步迁移到可撤销设备凭据。
- 配置缓存权限最小化，诊断包默认脱敏。
- 所有策略变更、标签赋予、路由发布和设备撤销写审计事件。
- 对 OpenAPI handler、ACL parser/compiler、snapshot decoder 做 fuzz。
- 发布物生成 SBOM并签名，桌面 daemon/helper 单独审计提权边界。

## 15. 文档体系

每个仓库文档职责如下。

### `xconnect-app/docs/overlay/`

```text
README.md                         # 用户入口
join-and-leave.md                 # CLI/App Join
status-and-diagnostics.md
platform-support.md
security-model.md
runtime-architecture.md
configuration-schema.md
troubleshooting.md
release-testing.md
```

### `accounts.svc.plus/docs/overlay/`

```text
architecture.md
api.md                            # 由 OpenAPI 派生
data-model.md
device-enrollment.md
acl-language.md
acl-compiler.md
configuration-projection.md
gateway-eventing.md
key-and-token-lifecycle.md
operations-runbook.md
```

### `playbooks/docs/xconnect/`

```text
gateway-deployment.md
gateway-upgrade.md
vault-secret-layout.md
tls-certificate-requirements.md
static-to-dynamic-migration.md
closure-verification.md
disaster-recovery.md
```

### 决策记录 ADR

至少建立：

- ADR-001：XConnect-APP 作为共享宿主，XConnect-One 作为内置产品插件，不新建客户端。
- ADR-002：Go shared core + 平台原生系统 VPN 入口。
- ADR-003：accounts 是 Overlay 唯一事实来源。
- ADR-004：Ansible 只做 Gateway bootstrap。
- ADR-005：Gateway 强制执行 ACL。
- ADR-006：完整签名 snapshot + generation，而非命令增量。
- ADR-007：L3 默认，L2 仅 Linux Gateway。
- ADR-008：Product Plugin API、权限边界和移动端静态集成策略。
- ADR-009：v1 仅使用 Xray-core/libXray，移除 sing-box runtime 和 fallback。

ADR 模板：

```markdown
# ADR-NNN 标题

- Status: proposed | accepted | superseded
- Date:
- Owners:

## Context
## Decision
## Alternatives considered
## Consequences
## Security impact
## Rollout and rollback
```

## 16. 分阶段开发计划

以下按两周 Sprint 估算；团队规模假设为 2 名 Go/后端、2 名客户端/平台、1 名基础设施/测试，可根据实际并行度调整。

### Phase 0：契约和基线（Sprint 1，2 周）

交付：

- 恢复/确认 `accounts.svc.plus` 可开发工作树。
- 固化现有 Overlay API OpenAPI v1。
- 固化 SignedConfig 和 GatewaySnapshot JSON Schema。
- 从当前 group_vars 导出 baseline fixture。
- 在 xconnect-app 建立 `overlay/` package 和 Runtime SPI。
- 建立 XConnect-APP Product Plugin API、manifest schema、HostServices fake 和 XConnect-One 内置插件骨架。
- 清除并禁止 sing-box dependency、adapter、config renderer、artifact 和 CI matrix；增加依赖与发布物扫描门禁。
- 将 closure 脚本接入 CI 的 check-only 模式。

退出条件：现有生产闭环不回归；OpenAPI 可生成 Go/Dart client；baseline snapshot golden 通过。

### Phase 1：`xconnect join` MVP（Sprint 2-3，4 周）

交付：

- 将原 overlayctl use case 迁入 xconnect-app shared core，并将二进制入口正式命名为 `xconnect`。
- 实现 `join/up/down/status/diagnose/leave`。
- 本地安全状态和可恢复 Join 状态机。
- Linux、macOS CLI 首批可用。
- Flutter UI 调用相同 Join use case。
- CLI 与 Flutter UI 均通过 XConnect-One 产品插件调用 shared use case，不直接依赖 Overlay 内部 package。
- 配置签名、generation、last-known-good 和 ACK。

退出条件：Linux/macOS 从干净机器执行一次命令加入；重复 Join 幂等；错误签名和中断恢复通过。

### Phase 2：Gateway 动态投影（Sprint 4-5，4 周）

交付：

- `xconnect-gateway-agent`。
- Node heartbeat v1、snapshot、apply-result API。
- group_vars importer。
- 静态/动态 shadow diff。
- `wg syncconf` 原子应用和回滚。
- 新 Ansible bootstrap role/Molecule 测试。

退出条件：新设备 Join 后不运行 Ansible即可成为 Gateway Peer；撤销在目标 SLA 内生效；控制面断开不影响已有隧道。

### Phase 3：动态 ACL（Sprint 6-7，4 周）

交付：

- ACL schema、parser、compiler、golden/fuzz。
- 控制面策略发布、激活、审计和回滚。
- Gateway nftables enforcement。
- 客户端 compiled policy enforcement。
- `xconnect policy explain`。

退出条件：恶意或禁用本地策略的客户端仍无法越权；策略更新原子；deny/撤销 SLA 达标。

### Phase 4：五平台闭环（Sprint 8-10，6 周）

交付：

- Windows Service 和安装升级。
- Android VpnService Join/配置接入。
- iOS/macOS Packet Tunnel Overlay profile 接入。
- iOS/Android 邀请链接和二维码。
- 五平台诊断包和状态模型统一。
- 平台 CI、真机 smoke 和 soak。

退出条件：五平台均完成 `enroll → connect → policy → config rotate → revoke`，并保存标准 evidence。

### Phase 5：清理与 GA（Sprint 11，2 周）

交付：

- 停用静态客户端 group_vars。
- 停用 `apply-playbooks-client` 产品路径。
- 完整用户、开发、运维和安全文档。
- SLO dashboard、告警、容量模型。
- 安全评审、恢复演练、签名发布物。

退出条件：连续两周 staging/小流量生产无 P0/P1；回滚演练通过；GA checklist 完成。

## 17. 工作流与 Issue 模板

Epic：

```markdown
# [EPIC] 标题

## Outcome
## User impact
## Scope / Non-scope
## Architecture links
## API/schema changes
## Security impact
## Milestones
## Test plan
## Rollout / rollback
## Definition of done
```

Feature：

```markdown
# [AREA] 标题

- Parent epic:
- Platforms:
- Feature flag:

## Acceptance criteria
## Compatibility
## Observability
## Test cases
## Documentation updates
```

Bug：

```markdown
# [BUG] 标题

- Version/generation:
- Platform/runtime:
- Expected/actual:
- Reproduction:
- Sanitized diagnostics:
- Regression test:
```

Pull Request checklist：

```markdown
- [ ] API/schema backward compatible or migration documented
- [ ] Unit/contract/integration cases added
- [ ] Platform cases listed
- [ ] Security and secret handling reviewed
- [ ] Metrics/logging added and redacted
- [ ] Rollout/rollback documented
- [ ] User/developer/operations docs updated
- [ ] Generated code and golden files current
```

## 18. Definition of Done

一个 Overlay 功能只有同时满足以下条件才完成：

- API、schema、数据迁移和兼容性已定义。
- 客户端与 Gateway 使用相同版本化契约。
- 单元、contract、集成和要求的平台测试通过。
- ACL 和恶意客户端绕过路径已评估。
- 日志无秘密且包含可关联诊断信息。
- 指标、dashboard 或明确的运维检查存在。
- 灰度、feature flag 和回滚路径验证过。
- 用户文档、开发文档、Runbook 和 ADR 同步更新。
- E2E evidence 可被机器检查，不仅依赖人工描述“可以连接”。

## 19. 首批 Backlog（建议执行顺序）

1. 修复或重新检出 `accounts.svc.plus` 本地工作树，确认原 overlayctl/API 实际源码版本，并建立 `overlayctl → xconnect` 重命名清单。
2. 定义 XConnect-APP Product Plugin API、manifest schema、HostServices 权限边界和兼容策略。
3. 固定 v1 core ID 为 `xray`，移除并用 CI 禁止 sing-box 依赖、适配器、配置和发布物。
4. 创建 Overlay OpenAPI v1 和 SignedConfig/GatewaySnapshot schemas。
5. 为现有 `group_vars` 和 Xray/WG 模板建立 golden fixtures。
6. 在 xconnect-app 增加 XConnect-One 内置插件、Runtime SPI、fake host 和 fake runtime。
7. 将原 overlayctl Join 状态机提取为 shared Go package，入口安装为 `xconnect`。
8. 建立 `xconnect join/status/diagnose` CLI。
9. 将 Flutter 登录/同步通过产品插件接入相同 use case。
10. 实现 snapshot signing、generation 和 last-known-good。
11. 实现 Gateway Agent shadow mode。
12. 编写 group_vars importer 和 static-vs-projected diff。
13. 切换到动态 `wg syncconf`。
14. 实现 ACL schema/compiler 和 gateway nftables backend。
15. 补齐 Windows、Android、iOS 平台闭环。
16. 删除静态客户端列表和过渡命令。

## 20. 关键风险和缓解

| 风险 | 缓解 |
|---|---|
| accounts 本地源码状态不完整 | Phase 0 首要恢复；以线上契约和 closure evidence 反向验证 |
| XConnect-One 当前以通用 Xray Secure Tunnel 为主，未闭环 WG-over-VLESS | 使用独立 Overlay profile，不破坏现有模式；feature flag 灰度 |
| VLESS/TCP 承载 UDP 的延迟/队头阻塞 | 保留 transport SPI；首期量化 SLO，后续增加直连 UDP/QUIC transport |
| 动态配置错误清空 Gateway peers | 完整签名 snapshot、last-known-good、空集保护、shadow diff |
| ACL 只在客户端执行可被绕过 | Gateway 强制执行；客户端策略仅作补充 |
| 五平台行为分叉 | shared use case + Runtime SPI + contract/golden；平台层保持薄 |
| iOS Packet Tunnel 内存限制 | 延续现有真机 soak 和内存采样，控制配置/规则规模 |
| 共享 Xray UUID 无法细粒度撤销 | 作为迁移债务；引入 per-device/short-lived transport credential |
| L2 广播扩大故障域 | L3 默认；L2 仅受控 Linux Gateway，单独授权和限速 |

---

本计划的核心原则是：保留已经证明可用的数据面，把产品化工作集中到共享 Join use case、版本化契约、动态 Gateway 投影和不可绕过的策略执行。Ansible 继续做它擅长的节点部署，XConnect-One Client 继续做它已经具备的五平台系统 VPN，accounts 控制面成为唯一动态事实来源。
