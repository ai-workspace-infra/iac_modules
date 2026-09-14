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
  instance_initiated_shutdown_behavior = "terminate"

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
