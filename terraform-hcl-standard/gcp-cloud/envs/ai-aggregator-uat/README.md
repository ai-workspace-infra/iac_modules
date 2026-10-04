# AI Aggregator UAT (GCP Spot)

This is a generated Terraform root. The environment declaration lives in
GitOps at `resources/xworktech.com/uat/gcp/ai-aggregator-vps-uat.yaml`.
Render it with the shared `gcp-cloud/scripts/generate.py` using `--resources`
and `--workdir envs/ai-aggregator-uat`. Generated state, inventory, and
variables are ignored. The shared renderer expands one gateway and four CPA
nodes into explicit Spot modules, with a 3600-second maximum runtime and
CPA service ports reachable only from gateway-tagged VMs.
