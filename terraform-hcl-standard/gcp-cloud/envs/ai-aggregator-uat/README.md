# AI Aggregator UAT (GCP Spot)

This directory is a generated Terraform root. Render it from
`config/resources/ai-aggregator-vps-uat.yaml` with
`scripts/generate_ai_aggregator.py` and inject `GCP_PROJECT_ID`, the operator
SSH public key, and fixed `/32` allowlists at runtime. Generated state,
inventory, and variables are intentionally ignored.

The contract expands one Gateway and four CPA nodes as explicit Spot module
blocks. Every node receives a 60-minute local shutdown guard and all CPA
service ports are limited to the VPC gateway tag.
