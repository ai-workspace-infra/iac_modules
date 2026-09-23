# UCloud Terraform standard

Reusable Terraform modules for UCloud networking, UHost compute, and Elastic IPs.
The provider source is `ucloud/ucloud` and the version constraint follows the
current 1.39 release line.

## Credentials and provider configuration

The provider accepts credentials from either provider variables or the official
environment variables. Prefer environment variables so secrets stay out of
configuration and tfvars:

```sh
export UCLOUD_PUBLIC_KEY="..."
export UCLOUD_PRIVATE_KEY="..."
export UCLOUD_PROJECT_ID="org-..."
export UCLOUD_REGION="cn-bj2"
```

`provider.tf` supports `TF_VAR_ucloud_public_key`, `TF_VAR_ucloud_private_key`,
`TF_VAR_ucloud_project_id`, and `TF_VAR_ucloud_region` as alternatives. The
credential variables are marked sensitive. Terraform state still contains
provider-managed infrastructure data, so use an appropriately protected state
backend.

Store runtime credentials in Vault KV v2 at
`kv/CICD/<env>/ucloud/<project_id>` (API path
`kv/data/CICD/<env>/ucloud/<project_id>`). The record fields are
`UCLOUD_PUBLIC_KEY`, `UCLOUD_PRIVATE_KEY`, `UCLOUD_PROJECT_ID`, and
`UCLOUD_REGION`; see the platform-ops-toolkit helper
[`scripts/ucloud/bootstrap_ucloud_auth_kv.sh`](https://github.com/ai-workspace-infra/platform-ops-toolkit/blob/main/scripts/ucloud/bootstrap_ucloud_auth_kv.sh).
The helper supports `write` and `check` and does not print credential values.
UCloud UHost uses the standard Terraform state contract. ULightHost is a
separate provider boundary and remains existing-resource inventory only.

## GitOps render

Put non-secret UHost declarations in the GitOps repository under
`resources/<project>/<env>/ucloud/<workspace>.yaml`. The renderer creates an
isolated Terraform root under `envs/<env>/<workspace>`:

```yaml
management_mode: terraform
provisioner: terraform
environment: uat
global:
  region: cn-bj2
  availability_zone: cn-bj2-03
network:
  name: ai-aggregator-uat
  cidr_blocks: [10.20.0.0/16]
  subnet_cidr_block: 10.20.1.0/24
hosts:
  - name: ai-aggregator-uhost
    instance_type: n-basic-2
    security_group_id: firewall-xxxxx
    key_pair_id: keypair-xxxxx
```

The provider credentials and backend credentials are injected by the
platform-ops workflow from Vault. A local render can be produced with:

```sh
python3 scripts/generate.py render \
  --resources "$GITOPS_ROOT/resources/svc.plus/uat/ucloud/ai-aggregator.yaml" \
  --workdir envs/uat/ai-aggregator
```

## Modules

- `modules/network`: creates a VPC and one subnet.
- `modules/compute`: creates one `ucloud_instance` (UHost); accepts existing
  image and security group IDs, optional VPC/subnet IDs, key pair or password
  login, user data, and deletion protection.
- `modules/eip`: creates a standalone Elastic IP. Associate it with an instance
  using the provider's `ucloud_eip_association` resource when needed.

Each module declares `required_providers` because Terraform resolves provider
source addresses in child modules independently.

## Example

`envs/dev` demonstrates querying an image with `data.ucloud_images`, creating a
VPC/subnet pair, then placing a UHost in that subnet. Supply account-specific
values at runtime:

```sh
terraform -chdir=terraform-hcl-standard/ucloud/envs/dev init
terraform -chdir=terraform-hcl-standard/ucloud/envs/dev plan \
  -var='availability_zone=cn-bj2-03' \
  -var='security_group_id=firewall-xxxxx'
```

Replace the example key pair ID in `envs/dev/main.tf` with an existing UCloud key
pair. Availability zones, image names, instance types, disk types, and EIP billing
options vary by region and account; confirm they are available before applying.

The modules contain one explicit resource each. For repeated resources, keep
resource descriptions in YAML and expand them in the repository's Python/Jinja2
generation layer as described in `../AGENTS.md`; do not add HCL `count`,
`for_each`, or `dynamic` blocks to environment configurations.
