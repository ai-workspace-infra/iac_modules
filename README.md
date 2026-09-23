[🇺🇸 English](README.md) | [🇨🇳 中文](README.zh.md)

# AI Workspace Infrastructure Modules (`iac_modules`)

`iac_modules` is the Infrastructure-as-Code repository of the AI Workspace platform. It consumes
cloud declarations from the sibling GitOps repository, renders explicit Terraform HCL from that YAML
with Python + Jinja2, applies it per environment, and emits a CMDB (`cmdb.json`) that the Ansible layer consumes. Terraform here
owns compute / network / storage / identity only — software configuration belongs to the playbooks
repo on the other side of the CMDB contract.

## Core paradigm

```
../gitops/resources/<project>/<env>/<provider>/<group>.yaml          declaration — the only hand-edited entry point
        │   scripts/generate.py render       loops run in Python + Jinja2, never inside HCL
        ▼
generated_hosts.tf                           one explicit module/resource block per host
terraform.auto.tfvars.json ──▶ variables.tf  the YAML `global` section
        │   terraform apply
        ▼
output "cmdb_runtime"                        runtime-only facts (ip / instance_id / resolved os_id)
        │   scripts/generate.py inventory    merges static YAML fields + runtime outputs
        ▼
cmdb.json + inventory.ini                    the IaC ↔ Ansible contract
```

Binding rules that follow from it — full text in
[`terraform-hcl-standard/AGENTS.md`](terraform-hcl-standard/AGENTS.md) and
[`skills/`](skills):

- **No control structures in HCL.** No `for_each` / `count` / `dynamic`, no `templatefile()` with
  `%{ for }` / `%{ if }`. Multiplicity is expanded at render time into uniquely named blocks.
- **No topology in HCL.** Regions, plans, instance counts, domains and host vars live in YAML.
- **No embedded scripts in HCL.** No `local-exec` provisioners, no `null_resource` shell/python.
- **One state namespace per environment.** `sit` / `uat` / `prod` never share a backend key.
  The canonical key is `terraform/<env>/<project>/<cloud>/<account>/<workspace>/terraform.tfstate`;
  its S3-compatible parameters come only from Vault `CICD/<env>/iac_state`.
- **Secrets never travel through files.** API keys arrive as `TF_VAR_*` env vars; generated
  credentials are pushed to Vault for Ansible to read back — never written to YAML, tfvars or
  handed forward on disk.
- **Rendered artifacts are not committed.** `generated_hosts.tf`, `terraform.auto.tfvars.json`,
  `cmdb.json`, `inventory.ini` are gitignored; a run directory tracks only `README.md` + `.gitignore`.

## Layers inside a provider tree

Every provider under `terraform-hcl-standard/` follows the same three-layer split — declaration,
reusable templates, composition logic — leaving run directories as pure Terraform workdirs.

| Layer | Path | Role | Tracked |
|-------|------|------|---------|
| Declaration | sibling `gitops/resources/<project>/<env>/<provider>/*.yaml` | Resource topology, account and bootstrap facts | external GitOps repo |
| Templates | `<provider>/templates/` | Shared `provider.tf`, `variables.tf`, `backend.tf`, `cloud-init.yaml` and their `.j2` renderers | ✅ |
| Composition | `<provider>/scripts/generate.py`, `provision.sh` | `render` + `inventory` subcommands, one-shot provisioning | ✅ |
| Modules | `<provider>/modules/<resource>/` | Reusable resource modules consumed by the rendered blocks | ✅ |
| Root modules | `<provider>/component/` (AWS), `<provider>/instance/` (GCP) | Per-resource Terraform roots with a `Makefile` each | ✅ |
| Run directories | `<provider>/envs/<name>/` | Terraform workdir — receives the rendered artifacts and holds the state | README + `.gitignore` only |
| Bootstrap | `<provider>/bootstrap/{state,lock,identity}` | Remote state bucket, lock table, deploy role/user — applied before anything else | ✅ |

## Providers and their maturity

| Provider | Path | Status | Modules | What exists today |
|----------|------|--------|---------|-------------------|
| AWS | `terraform-hcl-standard/aws-cloud/` | Production | 14 | Terragrunt bootstrap (`state` / `lock` / `identity`), `component/` roots, GitOps-owned `sit` + `uat` + `prod` declarations, render + inventory scripts |
| Vultr | `terraform-hcl-standard/vultr-vps/` | Production — reference implementation of the render pattern | 7 | Four run directories (`ai-workspace`, `dev`, `platform-ops-toolkit`, `site-migration-toolkit`), GitOps-owned environment declarations, `provision.sh` |
| Akamai Cloud / Linode | `terraform-hcl-standard/akamai-cloud/` | MVP — VPS provider tree | 3 | Linode compute, firewall, VPC and block storage modules; explicit renderer, CMDB/inventory and fixture validation |
| Alibaba Cloud | `terraform-hcl-standard/ali-cloud/` | Partial | 9 | Modules + bootstrap + `envs/dev`; declarations are external |
| GCP | `terraform-hcl-standard/gcp-cloud/` | Core baseline | 14 | Project/API, VPC, IAM/WIF, Vault VM, Artifact Registry and Cloud Run modules |
| Azure | `terraform-hcl-standard/azure-cloud/` | Skeleton | 14 | One `main.tf` per module; no run directories, no resource declarations |
| UCloud UHost | `terraform-hcl-standard/ucloud/` | Terraform standard | 3 | GitOps-driven UHost renderer and reusable network, compute, and EIP modules |
| ULightHost | external inventory | Existing resources | — | No Terraform provider; inventory and run records only |

`utils/` at the `terraform-hcl-standard/` root holds shared Python rendering and
provider/backend helpers (`renderer.py`, `render_provider_backend.py`).

The provider-neutral backend, Vault fields, key hierarchy and external-inventory
contract are documented in [`docs/howto/unified-iac-state-contract.md`](docs/howto/unified-iac-state-contract.md).

## Module catalog by domain

| Domain | AWS | Alibaba Cloud | Vultr | Akamai Cloud / Linode | GCP / Azure (skeleton) |
|--------|-----|---------------|-------|----------------------|------------------------|
| Identity & governance | `iam`, `landingzone` | `ram` | `iam` | Vault/CI token contract | `iam`, `landingzone` |
| Compute | `ec2`, `keypair`, `ami_lookup` | `ecs` | `compute`, `resize-instance` | `compute` | `ec2`, `keypair`, `ami_lookup` |
| Network | `vpc`, `sg`, `alb`, `nlb` | `vpc`, `alb`, `nlb` | `vpc` | `vpc`, per-host firewall | `vpc`, `sg`, `alb`, `nlb` |
| Data & storage | `rds`, `redis`, `msk`, `s3` | `rds`, `redis`, `oss` | `data_store`, `storage` | `storage` | `rds`, `redis`, `msk`, `s3` |
| Teardown | `bootstrap-destroy` | `bootstrap-destroy` | `bootstrap-destroy` | — | `bootstrap-destroy` |

> The GCP and Azure trees declare genuine `google_*` / `azurerm_*` resources but inherited the AWS
> directory names (`ec2`, `s3`, `msk`, `ami_lookup`). Naming is not normalized yet.

## Environments and resource groups

Three environments, each with its own YAML directory, its own run directory and its own state:
**`sit`** (integration), **`uat`** (pre-production), **`prod`**.

Resource groups are the unit of declaration inside an environment — one YAML per group, one
Terraform run per group:

| Group | Ansible group / tags | Carries |
|-------|----------------------|---------|
| `web-saas` | `web_saas`, `database` | Console / accounts / PostgreSQL SaaS hosts, including the public service domains Caddy terminates TLS for |
| `ai-workspace` | `ai_workspace`, `database` | The AI workspace application nodes |
| `infra-platform` | `infra_platform`, `database` | Shared platform services |
| `agent-proxy` | `agent_proxy` | Agent egress / proxy nodes |
| `action-runner` | `action_runner` | Self-hosted CI runners |
| `all-in-one` (`sit` only) | mixed | The whole stack collapsed onto a single SIT host |

`uat` and `prod` are deliberately separate declarations and separate states — the CMDB produced by a
run is the deploy source of truth for that environment, and a run must never be pointed at another
environment's host variables.

## Components outside Terraform

| Path | Contents |
|------|----------|
| `vpn-overlay/` | Cross-site L2/L3 overlay: `wireguard/`, `xray/`, `vxlan/`, `gretap/`, `config/sites.yaml`, topology diagrams |
| `skills/` | Binding specs — `IAC-Spec` (IaC red lines), `terraform-yaml-render-pattern` (the render pattern), `release-branch-policy` |
| `scripts/` | Repo-level helpers — `dynamic_inventory.py`, WireGuard key generation, gitleaks auto-fix, and `workflows/` helpers for Flux, Ansible, kubeconfig and xconfig |
| `.github/actions/` | Pipeline definitions — per-cloud landing-zone baselines, infrastructure resources, monitoring exporter/server, SSL certificate renewal |
| `.github/workflows/` | `validate-release-pr.yml` — the only workflow that runs in this repository |
| `example/` | Reference samples: Pulumi (Python) and plain Terraform for AWS / Azure / GCP |
| `docs/` | Bilingual documentation set — start at [`docs/README.md`](docs/README.md) |

## Quickstart

> These modules are built to be driven by pipelines and by `generate.py`; running `terraform` by hand
> inside a provider directory will not work, because run directories only exist after a render.

### Prerequisites

- Terraform >= 1.5.0
- Terragrunt >= 0.67.14 (AWS bootstrap only)
- Python 3 with `PyYAML` and `Jinja2` (`requirements.txt` installs these plus the Pulumi example deps)
- Provider credentials — AWS via the standard credential chain / OIDC, Vultr via `TF_VAR_vultr_api_key`, Akamai Cloud/Linode via `TF_VAR_linode_token` / `LINODE_TOKEN`

### 1. Bootstrap an account (once)

Account facts (bucket, lock table, role names) come from the external GitOps repo, not from this one:

```bash
git clone https://github.com/ai-workspace-infra/gitops.git ../gitops
cd terraform-hcl-standard/aws-cloud/bootstrap
BOOTSTRAP_CONFIG_PATH=../../../../gitops/resources/<project>/<env>/<provider>/bootstrap.yaml make bootstrap-init bootstrap-apply
```

Creates the S3 state bucket (versioned + encrypted), the DynamoDB lock table and the deploy
role/user. See [`aws-cloud/README.md`](terraform-hcl-standard/aws-cloud/README.md) for credential
modes and teardown.

### 2. Render, apply and produce the CMDB

```bash
export TF_VAR_vultr_api_key=...
cd terraform-hcl-standard/vultr-vps/scripts

RESOURCES=../../../../gitops/resources/<project>/uat/<provider>/web-saas.yaml \
WORKDIR=../envs/ai-workspace \
./provision.sh
```

`provision.sh` runs the four steps in order — `generate.py render` → `terraform init && apply` →
`generate.py inventory` → optional Ansible. To drive the steps individually:

```bash
python3 generate.py render    --resources ../../../../gitops/resources/<project>/uat/<provider>/web-saas.yaml --workdir ../envs/ai-workspace
terraform -chdir=../envs/ai-workspace init && terraform -chdir=../envs/ai-workspace apply
python3 generate.py inventory --resources ../../../../gitops/resources/<project>/uat/<provider>/web-saas.yaml --workdir ../envs/ai-workspace
```

### 3. Hand over to Ansible

The playbooks repo consumes `cmdb.json` through its dynamic inventory
(`playbooks/inventory/terraform_cmdb.py`) — it never reads tfstate. Re-run `generate.py inventory`
after every infrastructure change.

```bash
ansible web_saas -i ../../../../playbooks/inventory/terraform_cmdb.py -m ping
```

## Before you change anything

- [`terraform-hcl-standard/AGENTS.md`](terraform-hcl-standard/AGENTS.md) — binding Terraform constraints
- [`skills/IAC-Spec/SKILL.md`](skills/IAC-Spec/SKILL.md) — IaC red lines and the IaC ↔ config-as-code boundary
- [`skills/terraform-yaml-render-pattern/SKILL.md`](skills/terraform-yaml-render-pattern/SKILL.md) — the render pattern with its pre-commit checklist
- [`skills/release-branch-policy/SKILL.md`](skills/release-branch-policy/SKILL.md) — branch and release policy

Pre-commit self-check: `terraform fmt` clean, `terraform validate` passing, `generate.py render`
producing valid HCL, `ansible-inventory --graph` parsing the generated inventory, no rendered
artifacts or secrets staged.

## Known gaps

- Azure remains a skeleton; GCP core baseline modules are deployable through the GitOps declarations.
- Alibaba Cloud has modules and a development workspace; declarations are kept in GitOps when added.
- Renderers either require an explicit `--resources` / `RESOURCES` path or default to a declaration
  in the sibling GitOps checkout. Pass the GitOps declaration path when selecting a project,
  environment or provider.
- Documentation consolidation is tracked in [`docs/DOC_COVERAGE.md`](docs/DOC_COVERAGE.md).

## Docs / Links

- [Official website](https://www.svc.plus/)
- [ai-workspace-infra organization](https://github.com/ai-workspace-infra)
