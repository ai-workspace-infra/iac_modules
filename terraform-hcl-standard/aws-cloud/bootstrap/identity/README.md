# AWS Bootstrap Identity (Terraform / GitHub Actions OIDC)

此目录在原有 Terraform AK/SK 引导身份的基础上，新增 GitHub Actions OIDC 专用角色，便于无长生命周期凭证的 IaC 自动化。若 OIDC 服务不可用，仍可使用原有 Terraform IAM User + AssumeRole 路径作为应急逃逸出口。

## 资源概览

- `aws_iam_openid_connect_provider.github_actions`：GitHub Actions 公共 OIDC Provider（`https://token.actions.githubusercontent.com`）。
- `aws_iam_role.github_actions_deploy_role`：供 GitHub Actions 通过 OIDC 假设的角色。信任的仓库、分支和 tag 只从 GitOps 声明读取，不在 Terraform 模块中硬编码。
- `aws_iam_role_policy_attachment.github_actions_deploy_role_admin`：示例使用 AWS 托管策略 `AdministratorAccess`（实际项目请收敛至 S3 state / DynamoDB lock 所需的最小权限）。

## Terraform 输出

- `github_actions_oidc_provider_arn`：GitHub Actions OIDC Provider ARN。
- `github_actions_deploy_role_arn`：GitHub Actions OIDC AssumeRole ARN。
- 兼容保留：`iam_role_arn`（Terraform Deploy Role）、`terraform_user_name`（Terraform IAM User）。

## GitHub Actions 配置要点

Workflow 需要的权限：

```yaml
permissions:
  id-token: write
  contents: read
```

示例步骤（仅示例，不生成 workflow 文件）：

```yaml
- uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: <terraform output: github_actions_deploy_role_arn>
    aws-region: ap-northeast-1
```

可根据需要在后续步骤执行 Terraform CLI，使用 OIDC 方式取代长期 AK/SK。若 OIDC 服务异常，可切回输出的 `iam_role_arn` 与 `terraform_user_name` 路径。

## GitOps 信任策略

OIDC 信任策略的唯一声明位于 GitOps 的
`resources/svc.plus/prod/aws/github-actions-oidc.json`。bootstrap 参数也从同目录的
`bootstrap-identity.yaml` 读取。先把 `ai-workspace-infra/gitops` checkout 到 iac_modules
旁边，再显式设置输入路径：

```yaml
github_actions_oidc:
  config_path: github-actions-oidc.json
```

该 JSON 声明必须包含 GitHub OIDC Provider URL、`sts.amazonaws.com` audience、AWS role 名称和
允许的 `sub` 列表。生产声明允许 `ai-workspace-infra/platform-ops-toolkit` 的 `main` 与
`v*` tag，因此手工 main 部署和每日发布 tag 都能取得同一受控角色。缺少或不合法的声明会使
Terraform plan/apply 失败，避免回退到宽泛或陈旧的信任策略。

## 生产 state 导入

生产采用 GitOps 中的
`resources/svc.plus/prod/aws/bootstrap-identity.yaml`。它引用同目录中的 OIDC JSON，并声明唯一的
非敏感 state key：

```text
platform-ops-toolkit/prod/aws-cloud/bootstrap/identity/terraform.tfstate
```

`provider.tf` 的 S3 backend 故意不包含 endpoint、bucket 或 access key。生产 bootstrap
workflow 从 Vault `kv/data/CICD/prod/iac_state` 在 `terraform init` 时注入这些敏感参数，再仅导入：

- `aws_iam_openid_connect_provider.github_actions`
- `aws_iam_role.github_actions_deploy_role`
- `aws_iam_role_policy_attachment.github_actions_deploy_role_admin`

该 production bootstrap 配置设置 `create_role: false` 和 `create_user: false`，避免在 OIDC
adoption 中创建历史 Terraform 用户或角色。
