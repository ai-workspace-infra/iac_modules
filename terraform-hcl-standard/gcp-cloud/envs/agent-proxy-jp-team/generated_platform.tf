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
  create_network           = var.create_network
  project_id               = module.project.project_id
  region                   = var.region
  network_name             = var.network_name
  subnet_name              = var.subnet_name
  subnet_cidr              = var.subnet_cidr
  enable_nat               = var.enable_cloud_nat
  private_ip_google_access = var.private_ip_google_access
}








resource "google_compute_address" "spot_ip_agent_proxy_jp_team" {
  project      = module.project.project_id
  name         = "agent-team-prod-v2-ip"
  region       = var.region
  address_type = "EXTERNAL"
  network_tier = "PREMIUM"
}

module "spot_agent_proxy_jp_team" {
  source                = "../../modules/spot_vm"
  depends_on            = [module.project, module.network]
  project_id            = module.project.project_id
  name                  = "agent-proxy-jp-team"
  zone                  = "asia-northeast1-a"
  machine_type          = "n2-custom-2-2048"
  image                 = "projects/debian-cloud/global/images/family/debian-12"
  network               = module.network.network
  subnetwork            = module.network.subnet
  labels                = { "environment" : "prod", "pool" : "team", "role" : "team", "stack" : "prod-v2" }
  network_tags          = ["prod-v2-team"]
  public_ip             = true
  ssh_public_key        = var.ssh_public_key
  ssh_username          = var.ssh_username
  enable_oslogin        = true
  provisioning_model    = "STANDARD"
  deletion_protection   = true
  static_ip_address     = google_compute_address.spot_ip_agent_proxy_jp_team.address
  boot_disk_size_gb     = 20
  boot_disk_auto_delete = true
  require_data_disk     = false
}

# OS Login replaces metadata SSH keys; the deploy principal needs sudo on
# exactly this VM to run Ansible.
resource "google_compute_instance_iam_member" "spot_os_admin_login_agent_proxy_jp_team" {
  project       = module.project.project_id
  zone          = "asia-northeast1-a"
  instance_name = module.spot_agent_proxy_jp_team.name
  role          = "roles/compute.osAdminLogin"
  member        = "serviceAccount:${var.deploy_service_account}"
}

# Public service ports of this VM only. SSH stays on the spot_ssh rule below.
resource "google_compute_firewall" "spot_public_tcp_agent_proxy_jp_team" {
  project       = module.project.project_id
  name          = "agent-proxy-jp-team-public-tcp"
  network       = module.network.network
  direction     = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["prod-v2-team"]

  allow {
    protocol = "tcp"
    ports    = ["80", "443", "1443"]
  }
  allow {
    protocol = "udp"
    ports    = ["443"]
  }
}

resource "google_compute_firewall" "spot_ssh" {
  project       = module.project.project_id
  name          = "agent-proxy-jp-team-ssh"
  network       = module.network.network
  direction     = "INGRESS"
  source_ranges = ["54.199.179.163/32", "54.178.56.237/32", "35.235.240.0/20"]
  target_tags   = ["prod-v2-team"]

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
      "agent-proxy-jp-team" = {
        name               = module.spot_agent_proxy_jp_team.name
        public_ip          = module.spot_agent_proxy_jp_team.public_ip
        private_ip         = module.spot_agent_proxy_jp_team.private_ip
        self_link          = module.spot_agent_proxy_jp_team.self_link
        zone               = module.spot_agent_proxy_jp_team.zone
        project_id         = module.spot_agent_proxy_jp_team.project_id
        provisioning_model = module.spot_agent_proxy_jp_team.provisioning_model
      }
    }
    cloud_run_services = {
    }
  }
}
