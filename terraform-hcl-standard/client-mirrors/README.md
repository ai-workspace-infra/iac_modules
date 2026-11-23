# Client Dual-Mirror IaC (`dl.svc.plus` + `cn-dl.svc.plus`)

Automated Terraform + Vault KV v2 stack provisioning the shared multi-product client distribution mirrors for `svc.plus`:

- **Global Mirror (`https://dl.svc.plus`)**: Cloudflare R2 bucket (`apac`), R2 Custom Domain (`dl.svc.plus`), bucket CORS, and a bucket-scoped `Workers R2 Storage Bucket Item Write` Account API token (S3 access key + SHA-256 secret synced to `kv/prod/platform/storage/cloudflare-r2`).
- **CN Mirror (`https://cn-dl.svc.plus`)**: Aliyun `oss-cn-hongkong` OSS bucket (`public-read`, CORS, versioning, AES256), Aliyun CDN `download` domain (`scope = "overseas"` by default; switchable in `mirrors.yaml` since `svc.plus` holds an ICP filing), `limit_rate` throttling (`10m` after `1m`), optional HTTPS redirect & CloudMonitor `BPS` alarm, Cloudflare non-proxied CNAME, and a least-privilege RAM publisher user (AK/SK synced to `kv/prod/platform/storage/aliyun-oss`).

## Bootstrap (Reuse Existing Cloudflare / State Records + One-Time Aliyun Secret)

`kv/prod/serverless/cloudflare` (`CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`) and `kv/CICD/prod/iac_state` already exist in `https://vault.svc.plus` and are reused automatically. Only `kv/prod/platform/alicloud` needs one-time bootstrap if not yet written:

```bash
./scripts/bootstrap-admin-vault-kv.sh --provider cloudflare --preflight
./scripts/bootstrap-admin-vault-kv.sh --provider alicloud
```

Or check existing Vault status without writing:

```bash
./scripts/bootstrap-admin-vault-kv.sh --provider cloudflare --preflight
./scripts/bootstrap-admin-vault-kv.sh --provider alicloud --preflight
```

> [!TIP]
> SaaS/API preflight, Aliyun CDN verification TXT sync, API reconciliation, and end-to-end mirror smoke probes also live under `ai-workspace-infra/playbooks` (`roles/saas/client_mirrors/` + `configure_client_mirrors.yml`), while Terraform resource creation and remote state management remain here under `terraform-hcl-standard/client-mirrors/`.

## Render, Validate & Reconcile

```bash
python3 scripts/generate.py render \
  --resources ../../gitops/resources/svc.plus/prod/client-mirrors/mirrors.yaml \
  --workdir envs/svc-plus-prod

python3 scripts/generate.py check-hcl --root .
```

See `.github/workflows/client-mirrors-iac.yml` for the automated PR validation and protected `prod` `workflow_dispatch` (`plan` / `apply` / `verify`) pipeline.

> [!NOTE]
> - If `cn-dl.svc.plus` has not previously verified ownership under your Aliyun account, `scripts/ensure_aliyun_cdn_verify_txt.py` automatically queries `DescribeVerifyContent` and upserts the Cloudflare `verification.svc.plus` TXT record before `terraform apply`.
> - For Aliyun CDN edge HTTPS certificates without an existing CAS `cert_id`, issue/bind the CDN certificate in Aliyun CDN Console or pass `cdn_cas_cert_id` in `mirrors.yaml` to enable the 301 `https_force` rule, and optionally configure CDN Usage Cap (用量封顶) in Console or CloudMonitor (`cdn_alarm_contact_group`).
