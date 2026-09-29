terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

resource "aws_instance" "this" {
  ami           = var.instance.ami
  instance_type = var.instance.type
  subnet_id     = var.subnet_id

  vpc_security_group_ids = [var.sg_id]
  key_name               = var.keypair_name
  user_data              = var.user_data
  iam_instance_profile   = var.iam_instance_profile_name != null ? var.iam_instance_profile_name : try(aws_iam_instance_profile.vault_agent[0].name, null)

  instance_market_options {
    market_type = "spot"
    spot_options {
      spot_instance_type             = "one-time"
      instance_interruption_behavior = "terminate"
    }
  }

  tags = merge(var.tags, {
    Name       = "${var.name_prefix}-instance"
    Ephemeral  = "true"
    AutoExpire = "true"
  })
}

resource "aws_iam_role" "vault_agent" {
  count = var.vault_agent_iam_profile_enabled ? 1 : 0

  name = coalesce(var.vault_agent_iam_role_name, "${var.name_prefix}-vault-agent")
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
  tags = var.tags
}

resource "aws_iam_instance_profile" "vault_agent" {
  count = var.vault_agent_iam_profile_enabled ? 1 : 0

  name = coalesce(var.vault_agent_iam_role_name, "${var.name_prefix}-vault-agent")
  role = aws_iam_role.vault_agent[0].name
  tags = var.tags
}
