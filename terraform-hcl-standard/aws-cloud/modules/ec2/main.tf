resource "aws_instance" "this" {
  ami           = var.instance.ami
  instance_type = var.instance.type

  # 明确由 env 层传入，无任何自动推断
  subnet_id = var.subnet_id

  vpc_security_group_ids = [var.sg_id]

  key_name = var.keypair_name

  # The instance may be stopped, but termination must be explicitly unblocked.
  disable_api_termination = var.deletion_protection
  disable_api_stop        = false

  lifecycle {
    # Terraform requires prevent_destroy to be a literal, not a variable.
    # All instances created by this shared module are therefore protected.
    prevent_destroy = true
  }

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
