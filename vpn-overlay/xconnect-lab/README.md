# XConnect disposable cross-cloud lab

This root creates a disposable, self-hosted Linux data-plane lab with two
symmetrical nodes:

| Node | Role | Runtime baseline |
|---|---|---|
| XConnect-Gateway | `relay/service` (`role=relay`) | Independent Linux node, external WireGuard + external Xray, forwarding and relay health |
| XConnect-One | `controlled-client` | Independent Linux node, external WireGuard + external Xray, CLI-driven sync/config/start/join |

The UAT `gateway_provider` is `aws-spot`. Both Gateway and One are AWS EC2
one-time Spot instances attached to the existing UAT default VPC. EC2 selects
a default subnet and availability zone with capacity instead of pinning both
nodes to the lexicographically first subnet. The nodes retain
private-path access between them and SSH limited to the runner /32 by default. A
temporary operator `/32` SSH allowlist can be supplied separately for debugging.
The module
does not create another VPC, subnet, route table, internet gateway, or EC2 key
pair. It creates only the two Spot instances and their disposable least-privilege
security groups. The Gateway has TLS
443 for the Xray transport and TCP 8443 for the temporary lab API harness;
public WireGuard UDP 51820 is not opened. Terraform outputs both public SSH
addresses and the Gateway private transport address, plus the TLS/Zero URLs
and node roles.

Each Spot instance has a five-minute Terraform create timeout. A capacity
shortage therefore fails fast and reaches exact-run cleanup instead of holding
the 90-minute workflow without reaching runtime validation.

Public Gateway transport access is opt-in through
`gateway_transport_ingress_cidrs`, which defaults to an empty list. It accepts
at most two unique canonical IPv4 `/32` values, for example
`198.51.100.42/32`. Each value adds one inline Gateway security-group rule for
TCP 443 only. Empty values, non-canonical values, non-`/32` networks, IPv6,
`0.0.0.0/0`, and more than two entries are rejected. This does not open
SSH, TCP 8443, or WireGuard UDP to the supplied CIDRs. The separate
`ssh_debug_ingress_cidrs` input only adds TCP 22 to both disposable nodes for
the explicitly supplied operator `/32` values.

When the list is nonempty, `gateway_transport_access_enabled` is `true` and
`gateway_transport_ip` is the Gateway public IP so an external desktop can
reach the TLS transport. With the default empty list, desktop access is
disabled and `gateway_transport_ip` remains the Gateway private IP for the
existing co-located lab path. The module still creates exactly two one-time
Spot instances with the workflow-provided absolute expiry. The default
GitOps retention is 60 minutes. Historical 120-minute leases remain a
cleanup-only compatibility case; new apply runs use the current GitOps
default.

The workflow passes its absolute `expires_at` timestamp into both minimal
cloud-init bootstraps. Each bootstrap validates the canonical RFC3339 UTC
value, installs a root systemd timer with absolute `OnCalendar` and
`Persistent=true`, and powers off with `/sbin/poweroff` at expiry. The one-time
Spot request is configured for interruption termination; Terraform does not
manage the separate OS-initiated shutdown attribute on these Spot resources.
A Spot instance can still be reclaimed earlier by AWS; the one-time Spot
request options are not used as the runtime TTL, and rebooting does not extend
the absolute expiry.

This UAT validation module accepts only `gateway_provider = "aws-spot"`; it
does not initialize or require a Vultr provider.

XConnect Zero is the product control plane: formal Accounts APIs (devices,
networks, policy and signed config) plus the Portal admin UI. Both roles
consume their configuration from that Zero source; the Gateway consumes the
relay/service projection and One consumes the controlled-client projection.
The co-located `xconnect-zero-lab` process is an experimental API-compatible
lab controller used only for cloud joint debugging and disposable enrollment.
It is not the formal Accounts API, Portal, or a production configuration
source.

The client is pinned to `t4g.micro` (2 vCPU / 1 GiB) and the Gateway to
`t4g.small` (2 vCPU / 2 GiB). Both use an ARM64 Ubuntu image and expire at the
workflow-provided absolute deadline, currently 60 minutes for new apply runs.
Historical 120-minute leases are cleanup-only compatibility cases. The consuming workflow in
`platform-ops-toolkit/.github/workflows/xconnect-cloud-lab.yml` downloads
version-pinned project Release artifacts for the formal Gateway, One CLI and
external Xray, then bootstraps both nodes over SSH. Verification checks Gateway
role/bootstrap, WireGuard and Xray service
health, TLS/API health, a recent handshake on both nodes, private ping and
HTTP through the relay, CLI sync, and negative reachability after tunnel down.
No Cloud Run or Cloudflare Worker is a Gateway deployment target.

There are no containers or Terraform provisioners. Runtime addresses and
resource IDs are outputs; provider state remains in the configured remote
backend. The dedicated backend key is
`uat/xconnect-lab/xcl-RUN_ID-ATTEMPT/terraform.tfstate`.

Run `bash contract_test.sh` for the offline resource-boundary checks and
`terraform init -backend=false && terraform validate` for provider-backed
schema validation.
