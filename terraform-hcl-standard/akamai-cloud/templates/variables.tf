variable "region" {
  description = "默认 Akamai Cloud/Linode region"
  type        = string
  default     = "us-east"
}

variable "image" {
  description = "默认 Linode image，例如 linode/debian12"
  type        = string
  default     = "linode/debian12"
}

variable "type" {
  description = "默认 Linode plan，例如 g6-standard-1"
  type        = string
  default     = "g6-standard-1"
}

variable "name_prefix" {
  description = "实例 label 前缀"
  type        = string
  default     = ""
}

variable "user_data_file" {
  description = "cloud-init 文件路径"
  type        = string
  default     = "cloud-init.yaml"
}
