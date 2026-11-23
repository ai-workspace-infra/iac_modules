output "bucket" {
  value = alicloud_oss_bucket.this.bucket
}

output "endpoint" {
  value = "https://oss-${var.oss_region}.aliyuncs.com"
}

output "cdn_domain" {
  value = alicloud_cdn_domain_new.this.domain_name
}

output "cdn_cname" {
  value = alicloud_cdn_domain_new.this.cname
}

output "access_key_id" {
  value = alicloud_ram_access_key.ci_rw.id
}

output "access_key_secret" {
  value     = alicloud_ram_access_key.ci_rw.secret
  sensitive = true
}
