[🇺🇸 English](README.md) | [🇨🇳 中文](README.zh.md)

# AI Workspace Infrastructure Modules (iac_modules)

`iac_modules` is the core Infrastructure-as-Code (IaC) repository for the AI Workspace ecosystem. It provides cloud-neutral, multi-cloud GitOps orchestrations, standard Terraform/Terragrunt modules, and automated deployment pipelines for establishing a resilient, scalable AI infrastructure platform.

## About

- **Cloud-Neutral by Design**: Consistent resource abstraction across AWS, GCP, Azure, Alibaba Cloud, and Vultr.
- **GitOps Orchestration**: Automated multi-environment pipelines for bootstrap, landing zone, and account matrices.
- **VPN Overlay & Networking**: Includes configurations for establishing secure `vpn-overlay` (WireGuard, Xray) connections.
- **Standardized HCL**: A robust library of pre-configured `terraform-hcl-standard` modules for compute, networking, and security.

## Start TLDR

> **Note:** These modules are designed to be consumed by CI/CD pipelines (e.g., GitHub Actions) and orchestration tools rather than being run entirely manually.

### Prerequisites

Ensure you have the following installed if you plan to run modules locally:
- Terraform >= 1.5.0
- Terragrunt >= 0.50.0
- Cloud Provider CLIs (AWS CLI, gcloud, etc.)

### Usage

1. Multi-cloud Pipelines:
Refer to the `.github/workflows` directory for automated matrices:
```bash
.github/workflows/iac-pipeline-mutli-cloud-bootstrap.yaml
.github/workflows/iac-pipeline-mutli-cloud-landingzone-baseline.yaml
```

2. Standard Terraform Modules:
Navigate to the module directory and initialize:
```bash
cd terraform-hcl-standard/
terraform init
terraform plan
```

3. Setup VPN Overlay:
```bash
cd vpn-overlay/
# Follow specific instructions for wireguard or xray setup
```

## Repository Structure

- `terraform-hcl-standard/`: Core, reusable Terraform modules.
- `vpn-overlay/`: Secure networking and overlay configurations.
- `.github/workflows/`: GitOps pipelines and CI/CD matrices.
- `scripts/`: Helper scripts for environment setup and deployment.
- `example/`: Example implementations and reference architectures.

## Docs / Links

- [Official Website](https://www.svc.plus/)
- [CloudNativeSuite Documentation](https://github.com/ai-workspace-infra)
