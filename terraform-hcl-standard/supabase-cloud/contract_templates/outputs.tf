output "project_ref" {
  description = "Non-secret managed project identity; never a DSN."
  value       = supabase_project.this.id
}
