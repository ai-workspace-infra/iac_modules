# =============================================================================
# 由 generate.py 从 GitOps YAML 渲染生成 —— 请勿手工编辑
# 约束：循环在 Python/Jinja2 侧完成，生成 HCL 保持扁平、显式、可审计。
# =============================================================================








resource "linode_firewall" "fw_jp_free" {
  label           = "jp-free-firewall"
  inbound_policy  = "DROP"
  outbound_policy = "ACCEPT"


  inbound {
    label    = "ssh-1"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = "22"
    ipv4     = ["54.199.179.163/32"]
  }

  inbound {
    label    = "ssh-2"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = "22"
    ipv4     = ["54.178.56.237/32"]
  }


  inbound {
    label    = "ssh-ipv6-1"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = "22"
    ipv6     = ["::/0"]
  }


  inbound {
    label    = "http"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = "80"
    ipv4     = ["0.0.0.0/0"]
    ipv6     = ["::/0"]
  }


  inbound {
    label    = "https"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = "443"
    ipv4     = ["0.0.0.0/0"]
    ipv6     = ["::/0"]
  }


  inbound {
    label    = "tcp-1443"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = "1443"
    ipv4     = ["0.0.0.0/0"]
    ipv6     = ["::/0"]
  }


  inbound {
    label    = "udp-443"
    action   = "ACCEPT"
    protocol = "UDP"
    ports    = "443"
    ipv4     = ["0.0.0.0/0"]
    ipv6     = ["::/0"]
  }

}

module "compute_jp_free" {
  source = "../../../modules/compute_protected"

  label           = "jp-free"
  region          = "jp-tyo-3"
  type            = "g6-standard-1"
  image           = "linode/debian12"
  private_ip      = true
  firewall_id     = linode_firewall.fw_jp_free.id
  authorized_keys = ["ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDEsuS135lzjVvlH2iNrKz23lDFr7b686xs4d2HINP2glFPmgkgx1D6Dqwisb1UbhWHZmUUzRxXeNlE8fiaO0TXN/C0dsdUxgopnQRyakcA+gfJqqb38Syx8eqdC7mQy9ygOf763dWm6d/SYZ8WgNWLldk4QF9DiZOW9K22DMtY4/1Cqe/YE/WGpOMVr9T9BwvmOjarjWp2OPbx6RVlSOd735Mze5X+cJ9QqdLaisCiSoJ3j9S6dulcxm+7ghPfATvxlJyZWSrRrVqnmV45lPbeuUHlIEyuK1PK2MS6NtUP03ZhdRYJQKZLECpR5xAO/BliOtDdRornvHV1gutYD8/n3IS8sRVzYPvN9DuOhzBnBQUgciu2++R8zMfdVoH7mSbsE8u++vMcBk3UJ1Op0Ct+trl2bsnue96cAnoiII08JKwAaczD5uZIGhdkGV8zKnChNCjzCxP0i4PV/MYW04eWmH+E8G81zq4ZsvrvPYmilBbRrkwHvvbPba3SSb2F2As= shenlan@shenlandeMacBook-Air-2.local", "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPrlas7Hf97Llzj0enKLhkezOkxP+fjQr/AwPzNSS25w github-actions@cloud-neutral-toolkit"]
  user_data       = file(var.user_data_file)
  tags            = ["prod-v2", "free", "jp-tyo-3", "akamai-cloud", "amd64"]
}




output "cmdb_runtime" {
  description = "name -> runtime facts"
  value = {

    "jp-free" = {
      ip          = module.compute_jp_free.main_ip
      private_ip  = module.compute_jp_free.private_ip
      instance_id = module.compute_jp_free.instance_id
      ipv6        = module.compute_jp_free.ipv6
    }

  }
}

output "hosts_summary" {
  description = "name -> public IP"
  value = {

    "jp-free" = module.compute_jp_free.main_ip

  }
}
