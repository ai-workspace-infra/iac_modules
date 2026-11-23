# Client Mirrors PROD (`svc.plus`)

Runtime Terraform workdir for full-product-matrix dual mirrors (`dl.svc.plus` Cloudflare R2 and `cn-dl.svc.plus` Aliyun `cn-hongkong` OSS + `overseas` CDN).

Source declaration lives in `gitops/resources/svc.plus/prod/client-mirrors/mirrors.yaml`.
Render locally with:

```bash
python3 ../../scripts/generate.py render \
  --resources ../../../../gitops/resources/svc.plus/prod/client-mirrors/mirrors.yaml \
  --workdir .
```

All generated `.tf` / `.tfvars.json` files and `.terraform*` runtime artifacts are gitignored.
