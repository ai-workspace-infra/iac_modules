# Guance UAT workdir

声明输入：GitOps `resources/xworktech.com/uat/guance/observability.yaml`。尚未部署。

```bash
python3 scripts/generate.py render --resources /path/to/gitops/resources/xworktech.com/uat/guance/observability.yaml --workdir envs/uat
terraform -chdir=envs/uat init
terraform -chdir=envs/uat validate
```

本批仅支持 Dashboard。Provider 固定 0.1.0；API Key 由 Vault 注入 `TF_VAR_guance_api_key`。生产执行前必须补齐组织远端 backend；当前无 backend 配置仅用于离线验证，不执行 apply。不要将凭据放入清单或命令参数。

Manifest 必须有 `global`（environment=uat、workspace_alias、endpoint、region）和 `dashboards` 列表（id、name、description、tags、template）。endpoint/region 由真实工作空间确认，不提供假定免费站点默认值。
