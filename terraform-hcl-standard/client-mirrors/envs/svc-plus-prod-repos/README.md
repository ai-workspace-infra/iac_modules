# Client Repos PROD (`svc.plus`)

Runtime Terraform workdir for package repository dual mirrors (`repo.svc.plus` Cloudflare R2 and `cn-repo.svc.plus` Aliyun `cn-hongkong` OSS + CDN).

Source declaration lives in `gitops/resources/svc.plus/prod/client-mirrors/repos.yaml`.
Render locally with:

```bash
python3 ../../scripts/generate.py render --stack repos --workdir .
```

Or specify an explicit manifest:

```bash
python3 ../../scripts/generate.py render \
  --manifest ../../../../gitops/resources/svc.plus/prod/client-mirrors/repos.yaml \
  --workdir .
```

All generated `.tf` / `.tfvars.json` files and `.terraform*` runtime artifacts are gitignored.
