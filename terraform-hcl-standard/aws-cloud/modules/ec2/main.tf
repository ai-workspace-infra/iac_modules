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
  # EC2 rejects ModifyInstanceAttribute for Spot requests. The Spot request
  # itself already declares terminate-on-interruption, while on-demand hosts
  # retain the explicit shutdown policy used by production.
  instance_initiated_shutdown_behavior = var.spot_instance ? null : (var.max_runtime_minutes > 0 ? "terminate" : "stop")

  dynamic "instance_market_options" {
    for_each = var.spot_instance ? [true] : []
    content {
      market_type = "spot"

      spot_options {
        spot_instance_type             = "one-time"
        instance_interruption_behavior = "terminate"
      }
    }
  }

  # Ensure cloud images expose SSH even when their regional defaults differ.
  # The EC2 key pair is injected by cloud-init before user scripts run; this
  # explicitly enables the service that accepts that key. UAT Spot nodes also
  # retain their bounded runtime without a long-running CI scheduler.
  user_data = format(
    "#!/bin/sh\nset -eu\nsystemctl enable --now ssh || systemctl enable --now sshd || true\n%s",
    var.max_runtime_minutes > 0 ? format(
      "(\n  sleep %d\n  /sbin/shutdown -h now\n) >/var/log/instance-runtime-limit.log 2>&1 &\n",
      var.max_runtime_minutes * 60,
    ) : "",
  )

  # 明确由 env 层传入，无任何自动推断
  subnet_id = var.subnet_id

  vpc_security_group_ids = [var.sg_id]

  key_name = var.keypair_name

  # Production resources set this from GitOps. AWS then rejects any terminate
  # request until the protection is explicitly removed in a reviewed change.
  # UAT Spot nodes intentionally leave it false so their one-hour lifecycle
  # and immutable daily replacements can complete.
  disable_api_termination = var.deletion_protection
  disable_api_stop        = false

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-instance"
  })
}

resource "aws_eip" "this" {
  count  = var.elastic_ip ? 1 : 0
  domain = "vpc"

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-eip"
  })
}

resource "aws_eip_association" "this" {
  count         = var.elastic_ip ? 1 : 0
  instance_id   = aws_instance.this.id
  allocation_id = aws_eip.this[0].id
}
