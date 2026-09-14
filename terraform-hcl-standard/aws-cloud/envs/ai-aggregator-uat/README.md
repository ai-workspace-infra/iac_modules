# AI Aggregator UAT Terraform workdir

This directory is a generated, disposable workdir. The source declaration is
`${GITOPS_ROOT}/resources/svc.plus/uat/aws/ai-aggregator.yaml`.

```bash
export GITOPS_ROOT="${GITOPS_ROOT:-$(cd ../../../.. && pwd)/gitops}"
python3 ../../scripts/generate.py render \
  --resources ${GITOPS_ROOT}/resources/svc.plus/uat/aws/ai-aggregator.yaml \
  --workdir envs/ai-aggregator-uat
terraform -chdir=envs/ai-aggregator-uat init
terraform -chdir=envs/ai-aggregator-uat apply
python3 ../../scripts/generate.py inventory \
  --resources ${GITOPS_ROOT}/resources/svc.plus/uat/aws/ai-aggregator.yaml \
  --workdir envs/ai-aggregator-uat
```

Generated state and CMDB are temporary. The UAT workflow destroys the
resources after the 60-minute Spot test window.
