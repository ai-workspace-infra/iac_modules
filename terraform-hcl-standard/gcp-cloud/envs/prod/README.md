# GCP Open Platform PROD

这是 Terraform 渲染运行目录。资源唯一入口是 GitOps 仓库中的
`resources/xworktech.com/prod/gcp/open-platform-prod.yaml`；生产发布必须在 UAT 验证通过并
经过受保护环境审批后执行。

```bash
cd ../../
export GITOPS_ROOT="${GITOPS_ROOT:-$(cd ../../.. && pwd)/gitops}"
python3 scripts/generate.py render \
  --resources "${GITOPS_ROOT}/resources/xworktech.com/prod/gcp/open-platform-prod.yaml" \
  --workdir envs/prod
terraform -chdir=envs/prod init
terraform -chdir=envs/prod plan
```

设置 `TF_VAR_billing_account_id` 后才能创建项目；不要把 Billing ID 或其他密钥
写入 YAML、tfvars 或 Git。
