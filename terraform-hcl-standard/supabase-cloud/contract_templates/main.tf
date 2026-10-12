# Managed modes only. existing_external is rendered as a separate resource-free root.
resource "supabase_project" "this" {
  organization_id   = var.organization_id
  name              = var.project_name
  database_password = var.database_password
  region            = var.region
  instance_size     = var.instance_size

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [database_password]
    precondition {
      condition     = !var.strict_no_secret_state && var.ack_sensitive_state
      error_message = "Provider persists database_password in state; strict mode blocks this resource."
    }
    precondition {
      condition     = (var.management_mode == "create_new" && var.project_ref == null && !var.explicit_adoption) || (var.management_mode == "adopt_existing" && var.project_ref != null && var.explicit_adoption)
      error_message = "Choose create_new or explicit adopt_existing; external targets use a resource-free root."
    }
  }
}
