# GCP Open Platform UAT

这是 Terraform 渲染运行目录。资源唯一入口是 GitOps 仓库中的
`resources/xworktech.com/uat/gcp/open-platform-uat.yaml`；不要在此目录手写资源块。

```bash
cd ../../
export GITOPS_ROOT="${GITOPS_ROOT:-$(cd ../../.. && pwd)/gitops}"
python3 scripts/generate.py render \
  --resources "${GITOPS_ROOT}/resources/xworktech.com/uat/gcp/open-platform-uat.yaml" \
  --workdir envs/uat
terraform -chdir=envs/uat init
terraform -chdir=envs/uat plan
python3 scripts/generate.py inventory \
  --resources "${GITOPS_ROOT}/resources/xworktech.com/uat/gcp/open-platform-uat.yaml" \
  --workdir envs/uat
```

设置 `TF_VAR_billing_account_id` 后才能创建项目；不要把 Billing ID 或其他密钥
写入 YAML、tfvars 或 Git。先完成 UAT 验证，再使用 prod 清单执行生产计划。
