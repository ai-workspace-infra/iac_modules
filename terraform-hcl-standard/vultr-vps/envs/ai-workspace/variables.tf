# 全局变量。值由 generate.py 从 hosts.yaml 的 global 段渲染进
# terraform.auto.tfvars.json 后传入（即 “YAML 描述资源信息 -> variables.tf”）。
# 逐主机的资源不走变量，而是由 generate.py 用 Jinja2 渲染成 generated_hosts.tf
# 里的显式 module/resource 块（不使用 for_each/count 等 HCL 控制结构）。

variable "vultr_api_key" {
  description = "Vultr API Key，请通过环境变量 TF_VAR_vultr_api_key 提供（勿写入 YAML/tfvars）"
  type        = string
  sensitive   = true
}

variable "region" {
  description = "默认部署区域，主机未单独指定 region 时使用"
  type        = string
  default     = "nrt"
}

variable "name_prefix" {
  description = "实例 label 前缀"
  type        = string
  default     = "ai-workspace"
}

variable "user_data_file" {
  description = "cloud-init 脚本路径"
  type        = string
  default     = "cloud-init.yaml"
}
