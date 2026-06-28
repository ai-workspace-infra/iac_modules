[🇺🇸 English](README.md) | [🇨🇳 中文](README.zh.md)

# AI Workspace Infrastructure Modules (iac_modules)

`iac_modules` 是 AI Workspace 生态系统的核心基础设施即代码 (IaC) 仓库。它提供云中立的多云 GitOps 编排、标准的 Terraform/Terragrunt 模块，以及自动化的部署流水线，旨在构建弹性、可扩展的 AI 基础设施平台。

## 关于 (About)

- **云中立设计 (Cloud-Neutral)**：跨 AWS、GCP、Azure、阿里云和 Vultr 等环境提供一致的资源抽象。
- **GitOps 编排**：自动化的多环境流水线，支持引导层 (Bootstrap)、登陆区 (Landing Zone) 和多云账户矩阵。
- **VPN Overlay 与网络**：包含建立安全 `vpn-overlay`（WireGuard、Xray）连接的配置。
- **标准化 HCL 代码**：为计算、网络和安全提供强大且预配置的 `terraform-hcl-standard` 模块库。

## 快速开始 (Start TLDR)

> **注意：** 这些模块主要设计供 CI/CD 流水线（例如 GitHub Actions）和编排工具调用，而不是完全通过手动运行。

### 前置依赖 (Prerequisites)

如果计划在本地运行模块，请确保安装了以下工具：
- Terraform >= 1.5.0
- Terragrunt >= 0.50.0
- 云服务商 CLI 工具 (AWS CLI, gcloud 等)

### 使用 (Usage)

1. 多云流水线 (Multi-cloud Pipelines)：
请参考 `.github/workflows` 目录中自动化的矩阵配置：
```bash
.github/workflows/iac-pipeline-mutli-cloud-bootstrap.yaml
.github/workflows/iac-pipeline-mutli-cloud-landingzone-baseline.yaml
```

2. 标准 Terraform 模块：
进入模块目录并初始化：
```bash
cd terraform-hcl-standard/
terraform init
terraform plan
```

3. 配置 VPN Overlay：
```bash
cd vpn-overlay/
# 根据具体说明进行 wireguard 或 xray 配置
```

## 仓库结构 (Repository Structure)

- `terraform-hcl-standard/`: 核心且可重用的 Terraform 模块。
- `vpn-overlay/`: 安全网络与覆盖网络配置。
- `.github/workflows/`: GitOps 流水线和 CI/CD 矩阵。
- `scripts/`: 环境搭建与部署的辅助脚本。
- `example/`: 示例实现与参考架构。

## 文档 / 链接 (Docs / Links)

- [官方网站](https://www.svc.plus/)
- [CloudNativeSuite 文档](https://github.com/ai-workspace-infra)
