module "project" {
  source             = "../../modules/project"
  create_project     = var.create_project
  project_id         = var.project_id
  name               = var.project_name
  organization_id    = var.organization_id
  billing_account_id = var.billing_account_id
}


module "network" {
  source                   = "../../modules/network"
  depends_on               = [module.project]
  project_id               = module.project.project_id
  region                   = var.region
  network_name             = var.network_name
  subnet_name              = var.subnet_name
  subnet_cidr              = var.subnet_cidr
  enable_nat               = var.enable_cloud_nat
  private_ip_google_access = var.private_ip_google_access
}







module "retained_data_disk_web_saas_prod_v2_data" {
  source     = "../../modules/persistent_data_disk"
  project_id = module.project.project_id
  name       = "web-saas-prod-v2-data"
  zone       = "asia-east1-a"
  size_gb    = 100
  disk_type  = "pd-balanced"
}

# Keep attachment lifecycle separate from the existing VM resource. This lets
# Terraform add the independent disk without changing the VM module arguments.
resource "google_compute_attached_disk" "retained_data_disk_web_saas_prod_v2_data" {
  depends_on  = [module.spot_web_saas_prod_v2]
  project     = module.project.project_id
  zone        = "asia-east1-a"
  instance    = module.spot_web_saas_prod_v2.self_link
  disk        = module.retained_data_disk_web_saas_prod_v2_data.id
  device_name = "web-saas-prod-v2-data"
  mode        = "READ_WRITE"
}

resource "google_compute_address" "spot_ip_web_saas_prod_v2" {
  project      = module.project.project_id
  name         = "web-saas-prod-v2-ip"
  region       = var.region
  address_type = "EXTERNAL"
  network_tier = "PREMIUM"
}

module "spot_web_saas_prod_v2" {
  source                 = "../../modules/spot_vm"
  depends_on             = [module.project, module.network]
  project_id             = module.project.project_id
  name                   = "web-saas-prod-v2"
  zone                   = "asia-east1-a"
  machine_type           = "e2-medium"
  image                  = "projects/debian-cloud/global/images/debian-12-bookworm-v20261014"
  network                = module.network.network
  subnetwork             = module.network.subnet
  labels                 = { "environment" : "prod", "role" : "control", "stack" : "prod-v2" }
  network_tags           = ["prod-v2"]
  public_ip              = true
  ssh_public_key         = var.ssh_public_key
  ssh_username           = var.ssh_username
  enable_oslogin         = true
  provisioning_model     = "STANDARD"
  deletion_protection    = true
  static_ip_address      = google_compute_address.spot_ip_web_saas_prod_v2.address
  boot_disk_size_gb      = 30
  boot_disk_auto_delete  = true
  has_external_data_disk = true
}

# OS Login replaces metadata SSH keys; the deploy principal needs sudo on
# exactly this VM to run Ansible.
resource "google_compute_instance_iam_member" "spot_os_admin_login_web_saas_prod_v2" {
  project       = module.project.project_id
  zone          = "asia-east1-a"
  instance_name = module.spot_web_saas_prod_v2.name
  role          = "roles/compute.osAdminLogin"
  member        = "serviceAccount:${var.deploy_service_account}"
}

# Public service ports of this VM only. SSH stays on the spot_ssh rule below.
resource "google_compute_firewall" "spot_public_tcp_web_saas_prod_v2" {
  project       = module.project.project_id
  name          = "web-saas-prod-v2-https"
  network       = module.network.network
  direction     = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["prod-v2"]

  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
  allow {
    protocol = "udp"
    ports    = ["443"]
  }
}

# Service traffic for this VM is accepted only from declared source tags or ranges.
resource "google_compute_firewall" "spot_private_tcp_web_saas_prod_v2" {
  project       = module.project.project_id
  name          = "web-saas-prod-v2-private-db"
  network       = module.network.network
  direction     = "INGRESS"
  source_ranges = ["10.74.0.0/24"]

  allow {
    protocol = "tcp"
    ports    = ["15433"]
  }
}

resource "google_compute_firewall" "spot_ssh" {
  project       = module.project.project_id
  name          = "web-saas-prod-v2-ssh"
  network       = module.network.network
  direction     = "INGRESS"
  source_ranges = ["54.199.179.163/32", "54.178.56.237/32", "35.235.240.0/20"]
  target_tags   = ["prod-v2"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

output "platform_runtime" {
  description = "Runtime facts consumed by the CMDB renderer."
  value = {
    project_id     = module.project.project_id
    project_number = module.project.project_number
    cloud_run_uri  = null
    oidc_provider  = var.workload_identity_provider
    deploy_account = var.deploy_service_account
    vault_private_ips = {
    }
    vault_public_ips = {
    }
    vault_self_links = {
    }
    spot_instances = {
      "web-saas-prod-v2" = {
        name               = module.spot_web_saas_prod_v2.name
        public_ip          = module.spot_web_saas_prod_v2.public_ip
        private_ip         = module.spot_web_saas_prod_v2.private_ip
        self_link          = module.spot_web_saas_prod_v2.self_link
        zone               = module.spot_web_saas_prod_v2.zone
        project_id         = module.spot_web_saas_prod_v2.project_id
        provisioning_model = module.spot_web_saas_prod_v2.provisioning_model
        persistent_data_disks = [
          {
            name        = module.retained_data_disk_web_saas_prod_v2_data.name
            id          = module.retained_data_disk_web_saas_prod_v2_data.id
            zone        = "asia-east1-a"
            device_name = "web-saas-prod-v2-data"
            mount_path  = "/data"
          },
        ]
      }
    }
    cloud_run_services = {
    }
  }
}
