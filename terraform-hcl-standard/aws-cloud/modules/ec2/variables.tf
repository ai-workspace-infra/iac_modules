variable "name_prefix" {
  type        = string
  description = "Prefix for EC2 Name tag"
}

variable "instance" {
  type = object({
    type = string
    ami  = string
  })
  description = "Instance config"
}

variable "subnet_id" {
  type        = string
  default     = null
  description = "Optional subnet ID; null lets AWS select an AZ in the default VPC"
}

variable "sg_id" {
  type        = string
  description = "Security Group ID"
}

variable "keypair_name" {
  type        = string
  description = "KeyPair name"
}

variable "ssh_port" {
  type        = number
  description = "TCP port exposed by sshd"
  default     = 22

  validation {
    condition     = var.ssh_port >= 1 && var.ssh_port <= 65535
    error_message = "ssh_port must be between 1 and 65535."
  }
}

variable "tags" {
  type        = map(string)
  description = "Common tags"
}

variable "elastic_ip" {
  type        = bool
  description = "Allocate and associate an Elastic IP"
  default     = false
}

variable "deletion_protection" {
  type        = bool
  description = "Enable AWS EC2 API termination protection; production changes must explicitly disable it through GitOps before termination"
  default     = false
}

variable "spot_instance" {
  type        = bool
  description = "Launch the instance as a one-time EC2 Spot request"
  default     = false
}

variable "max_runtime_minutes" {
  type        = number
  description = "Terminate the instance this many minutes after boot; 0 disables the runtime limit"
  default     = 0

  validation {
    condition     = var.max_runtime_minutes >= 0
    error_message = "max_runtime_minutes must be zero or a positive number."
  }
}
