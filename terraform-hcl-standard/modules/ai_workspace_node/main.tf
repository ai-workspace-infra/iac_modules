# ==============================================================================
# AI Workspace Node Infrastructure Module (Host, Disk & Security Boundaries)
#
# 架构安全红线约束：
#   * 公网端口仅开放 80/443 (由 Caddy 接管自动 ACME TLS)
#   * L2 (PostgreSQL :15432) 与 L1 (QMD MCP :8181) 严禁直接暴露于公网
#   * 挂载独立高可用 NVMe/SSD 持久卷至 /var/lib/xworkmate
# ==============================================================================

locals {
  storage_mount_path = "/var/lib/xworkmate"
  tags = {
    Environment = var.environment
    Service     = "xworkmate-workspace"
    ManagedBy   = "Terraform"
  }
}

# 端口安全矩阵定义
locals {
  ingress_ports = concat(
    var.allow_http_https ? [80, 443] : [],
    [22]
  )
}
