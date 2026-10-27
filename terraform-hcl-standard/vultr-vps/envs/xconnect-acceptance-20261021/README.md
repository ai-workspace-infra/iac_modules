# Isolated XConnect node acceptance

Source: GitOps resources/xconnect-node-acceptance/uat/vultr/node-20261021.yaml.
Dedicated backend key: uat/xconnect-node-acceptance/20261021/terraform.tfstate.
One temporary Tokyo instance, 2 vCPU/2 GB/65 GB root; separate 25 GB high_perf data volume.
This workspace must never read an existing production state or register into production ingestion.
Keep state and provider credentials protected. Cleanup requires exact instance/volume/key IDs and separate authorization.
