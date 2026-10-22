variable "environment" {
  description = "Target deployment environment (dev, uat, prod)"
  type        = string
  default     = "uat"
}

variable "instance_name" {
  description = "Name identifier for the AI Workspace node"
  type        = string
  default     = "ai-workspace-node-01"
}

variable "domain_name" {
  description = "Public domain name pointing to the workspace node (e.g. bridge.example.com)"
  type        = string
  default     = ""
}

variable "data_volume_size_gb" {
  description = "Persistent data volume size in GB for L2/L3 storage (/var/lib/xworkmate)"
  type        = number
  default     = 100
}

variable "allow_ssh_cidrs" {
  description = "CIDR blocks allowed for SSH access (:22)"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "allow_http_https" {
  description = "Whether to allow public ingress on 80/443 for Caddy TLS termination"
  type        = bool
  default     = true
}
