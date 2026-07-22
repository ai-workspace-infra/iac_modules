resource "vultr_instance" "replacement" {
  label       = var.label
  region      = var.region
  plan        = var.target_plan
  os_id       = var.snapshot_id == null ? var.os_id : null
  snapshot_id = var.snapshot_id
  enable_ipv6 = var.enable_ipv6
  backups     = var.backups ? "enabled" : "disabled"
  tags        = concat(var.tags, ["resize-replacement", "resize-operation-${var.operation_id}"])
  vpc_ids     = var.vpc_id == null ? [] : [var.vpc_id]
  ssh_key_ids = var.ssh_key_ids
  user_data   = var.user_data

  dynamic "backups_schedule" {
    for_each = var.backups ? [1] : []
    content {
      type = var.backup_schedule_type
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}
