provider "ucloud" {
  public_key  = var.ucloud_public_key
  private_key = var.ucloud_private_key
  project_id  = var.ucloud_project_id
  region      = var.ucloud_region
}
