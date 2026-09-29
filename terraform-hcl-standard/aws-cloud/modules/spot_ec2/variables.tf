variable "name_prefix" {
  type        = string
  description = "Prefix for the temporary EC2 Name tag"
}

variable "instance" {
  type = object({
    type = string
    ami  = string
  })
}

variable "subnet_id" { type = string }
variable "sg_id" { type = string }
variable "keypair_name" { type = string }
variable "tags" { type = map(string) }

variable "iam_instance_profile_name" {
  type        = string
  description = "Optional pre-created IAM instance profile name for instance runtime identity"
  default     = null
}

variable "vault_agent_iam_profile_enabled" {
  type        = bool
  description = "Create a minimal EC2-trusted IAM role/profile for Vault Agent AWS IAM auto-auth"
  default     = false
}

variable "vault_agent_iam_role_name" {
  type        = string
  description = "Optional explicit name for the Vault Agent IAM role and instance profile"
  default     = null
}

variable "user_data" {
  type        = string
  description = "Non-secret cloud-init payload, including the UAT TTL guard"
  default     = ""
}
