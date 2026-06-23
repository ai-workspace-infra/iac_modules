variable "label" {
  description = "实例名称"
  type        = string
}

variable "region" {
  description = "Vultr 区域代码"
  type        = string
}

variable "plan" {
  description = "Vultr 计费套餐 (例如 vc2-1c-1gb)"
  type        = string
}

variable "os_id" {
  description = "操作系统 ID，参考 Vultr 文档 (例：215 为 Ubuntu 22.04)"
  type        = number
}

variable "enable_ipv6" {
  description = "是否启用 IPv6"
  type        = bool
  default     = true
}

variable "backups" {
  description = "启用自动备份"
  type        = bool
  default     = false
}

variable "tags" {
  description = "实例标签列表"
  type        = list(string)
  default     = []
}

variable "vpc_id" {
  description = "可选的 VPC ID，将实例加入私网"
  type        = string
  default     = null
}

variable "ssh_key_ids" {
  description = "已上传的 SSH Key ID 列表"
  type        = list(string)
  default     = []
}

variable "user_data" {
  description = "cloud-init 用户数据"
  type        = string
  default     = ""
}

resource "vultr_instance" "this" {
  label        = var.label
  region       = var.region
  plan         = var.plan
  os_id        = var.os_id
  enable_ipv6  = var.enable_ipv6
  backups      = var.backups ? "enabled" : "disabled"
  tags         = var.tags
  vpc_ids      = var.vpc_id == null ? [] : [var.vpc_id]
  ssh_key_ids  = var.ssh_key_ids
  user_data    = var.user_data
}

output "instance_id" {
  value       = vultr_instance.this.id
  description = "实例 ID"
}

output "main_ip" {
  value       = vultr_instance.this.main_ip
  description = "主公网 IP"
}

output "default_password" {
  value       = vultr_instance.this.default_password
  description = "系统生成密码（如未使用 SSH Key 时）"
  sensitive   = true
}
