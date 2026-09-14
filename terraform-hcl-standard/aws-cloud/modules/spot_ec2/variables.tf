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
variable "user_data" {
  type        = string
  description = "Non-secret cloud-init payload, including the UAT TTL guard"
  default     = ""
}
