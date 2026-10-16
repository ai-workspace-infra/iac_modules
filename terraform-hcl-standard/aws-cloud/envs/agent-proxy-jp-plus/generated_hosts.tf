# =============================================================================
# 由 generate.py 从 hosts.yaml 渲染生成 —— 请勿手工编辑
# 重新生成: python3 generate.py render
#
# 约束: 不使用 for_each/count/dynamic 等 HCL 控制结构。
# 每台主机、每个 SSH key 都渲染成独立的显式 module/resource/data 块。
# =============================================================================

resource "aws_key_pair" "ai_workspace_admin" {
  key_name   = "ai-workspace-admin"
  public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPrlas7Hf97Llzj0enKLhkezOkxP+fjQr/AwPzNSS25w github-actions@cloud-neutral-toolkit"
}

data "aws_vpc" "default_jp_plus" {
  provider = aws
  default  = true
}

data "aws_subnets" "default_jp_plus" {
  provider = aws
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default_jp_plus.id]
  }
}


# This host is intentionally pinned to an immutable AMI.  Production hosts
# with deletion protection must not be replaced merely because an upstream
# "most recent" image query starts returning a newer image.

resource "aws_security_group" "sg_jp_plus" {
  provider    = aws
  name_prefix = "jp-plus-sg"
  vpc_id      = data.aws_vpc.default_jp_plus.id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 1443
    to_port     = 1443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

module "compute_jp_plus" {
  source = "../../modules/ec2"
  providers = {
    aws = aws
  }

  # Keep the AWS console Name tag concise; the Terraform module/resource
  # address still uses `hid` and therefore remains state-compatible.
  name_prefix = var.name_prefix != "" ? "${var.name_prefix}-jp-plus" : "jp-plus"

  instance = {
    type = "c8gd.medium"
    ami  = "ami-0f3f8081a20023c18"
  }

  # No subnet/AZ is forced by default. AWS chooses an available AZ in the
  # default VPC, avoiding capacity failure caused by pinning to the first
  # subnet returned by the API.
  subnet_id           = null
  sg_id               = aws_security_group.sg_jp_plus.id
  keypair_name        = aws_key_pair.ai_workspace_admin.key_name
  ssh_port            = 22
  elastic_ip          = true
  deletion_protection = true
  spot_instance       = false
  max_runtime_minutes = 0

  tags = merge(
    { for t in concat([var.name_prefix], ["prod-v2", "plus", "ap-northeast-1", "aws-cloud", "arm64"]) : "Tag_${t}" => "true" if t != "" },
    { Name = var.name_prefix != "" ? "${var.name_prefix}-jp-plus" : "jp-plus" }
  )
}


output "cmdb_runtime" {
  description = "name -> {ip, instance_id, os_id}"
  value = {
    "jp-plus" = {
      ip          = module.compute_jp_plus.public_ip
      private_ip  = module.compute_jp_plus.private_ip
      instance_id = module.compute_jp_plus.instance_id
      os_id       = "ami-0f3f8081a20023c18"
    }
  }
}

output "hosts_summary" {
  description = "name -> public_ip"
  value = {
    "jp-plus" = module.compute_jp_plus.public_ip
  }
}
