variable "availability_zone" {
  description = "UCloud availability zone, such as cn-bj2-03."
  type        = string
}

variable "image_name_regex" {
  description = "Regular expression used to find the desired base image."
  type        = string
  default     = "^Ubuntu 22.04"
}

variable "security_group_id" {
  description = "Existing UCloud firewall security group ID."
  type        = string
}

variable "instance_type" {
  description = "UHost type supported by the selected zone."
  type        = string
  default     = "n-basic-2"
}

data "ucloud_images" "ubuntu" {
  availability_zone = var.availability_zone
  name_regex        = var.image_name_regex
  image_type        = "base"
}

module "network" {
  source = "../../modules/network"

  name              = "dev-network"
  tag               = "dev"
  cidr_blocks       = ["10.20.0.0/16"]
  subnet_cidr_block = "10.20.1.0/24"
}

module "compute" {
  source = "../../modules/compute"

  name              = "dev-uhost"
  availability_zone = var.availability_zone
  image_id          = data.ucloud_images.ubuntu.images[0].id
  instance_type     = var.instance_type
  security_group_id = var.security_group_id
  vpc_id            = module.network.vpc_id
  subnet_id         = module.network.subnet_id
  login_mode        = "KeyPair"
  key_pair_id       = "replace-with-existing-keypair-id"
}

output "instance_id" {
  value = module.compute.instance_id
}

output "instance_ip_set" {
  value = module.compute.ip_set
}

output "network_ids" {
  value = {
    vpc_id    = module.network.vpc_id
    subnet_id = module.network.subnet_id
  }
}
