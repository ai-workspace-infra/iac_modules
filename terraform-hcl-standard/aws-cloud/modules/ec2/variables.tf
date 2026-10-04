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
  description = "Subnet ID where EC2 instance will be launched"
}

variable "sg_id" {
  type        = string
  description = "Security Group ID"
}

variable "keypair_name" {
  type        = string
  description = "KeyPair name"
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
  description = "Prevent Terraform and EC2 API termination"
  default     = false
}
