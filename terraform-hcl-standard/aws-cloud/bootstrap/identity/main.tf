#
# GitHub Actions OIDC Provider & IAM Role for Terraform Deployments
# -----------------------------------------------------------------
resource "aws_iam_openid_connect_provider" "github_actions" {
  url = local.github_actions_provider_url

  client_id_list = [local.github_actions_audience]

  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  lifecycle {
    precondition {
      condition     = local.github_actions_oidc_config_path != null
      error_message = "Provide the GitOps OIDC declaration with github_actions_oidc.config_path in bootstrap YAML or github_actions_oidc_config_path."
    }
    precondition {
      condition     = local.github_actions_provider_url == "https://token.actions.githubusercontent.com"
      error_message = "GitHub Actions OIDC provider_url must be https://token.actions.githubusercontent.com."
    }
    precondition {
      condition     = local.github_actions_audience == "sts.amazonaws.com"
      error_message = "GitHub Actions OIDC audience must be sts.amazonaws.com."
    }
    precondition {
      condition     = local.github_actions_account_id == tostring(local.account.account_id)
      error_message = "GitOps OIDC AWS account_id must match the bootstrap account."
    }
  }
}

data "aws_iam_policy_document" "github_actions_oidc_assume_role" {
  override_policy_documents = [
    templatefile(
      "${path.module}/policies/github-actions-deploy-assume-role.json",
      {
        oidc_provider_arn = aws_iam_openid_connect_provider.github_actions.arn
        audience          = local.github_actions_audience
        subjects_json     = jsonencode(local.github_actions_subjects)
      }
    )
  ]
}

resource "aws_iam_role" "github_actions_deploy_role" {
  name = local.github_actions_role_name

  assume_role_policy = data.aws_iam_policy_document.github_actions_oidc_assume_role.json

  tags = merge(
    {
      Name        = local.github_actions_role_name
      Environment = coalesce(try(local.account.environment, null), local.environment)
    },
    try(local.account.tags, {}),
    local.extra_tags,
  )

  lifecycle {
    precondition {
      condition     = length(local.github_actions_subjects) > 0
      error_message = "GitOps OIDC declaration must define at least one permitted GitHub Actions subject."
    }
    precondition {
      condition     = local.github_actions_role_name != null && trimspace(local.github_actions_role_name) != ""
      error_message = "GitOps OIDC declaration must define spec.aws.role_name."
    }
    precondition {
      condition     = local.github_actions_role_arn == "arn:aws:iam::${local.github_actions_account_id}:role/${local.github_actions_role_name}"
      error_message = "GitOps OIDC role_arn must match spec.aws.account_id and spec.aws.role_name."
    }
    precondition {
      condition = alltrue([
        for subject in local.github_actions_subjects : startswith(subject, "repo:ai-workspace-infra/platform-ops-toolkit:")
      ]) && contains(local.github_actions_subjects, "repo:ai-workspace-infra/platform-ops-toolkit:ref:refs/heads/main") && contains(local.github_actions_subjects, "repo:ai-workspace-infra/platform-ops-toolkit:ref:refs/tags/v*") && contains(local.github_actions_subjects, "repo:ai-workspace-infra/platform-ops-toolkit:environment:production")
      error_message = "GitOps OIDC subjects must be restricted to platform-ops-toolkit and include main, v* tags, and the production environment subject."
    }
  }
}

resource "aws_iam_role_policy_attachment" "github_actions_deploy_role_admin" {
  role       = aws_iam_role.github_actions_deploy_role.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

#
# IAM Role: Terraform Deploy Role
# ----------------------------------------
data "aws_iam_policy_document" "terraform_deploy_assume_role" {
  override_policy_documents = [
    templatefile(
      "${path.module}/policies/terraform-deploy-assume-role.json",
      {
        account_id          = local.account.account_id
        terraform_user_name = local.config_terraform_user
      }
    )
  ]
}

resource "aws_iam_role" "terraform_deploy_role" {
  count = local.create_role ? 1 : 0

  name               = local.role_name
  assume_role_policy = data.aws_iam_policy_document.terraform_deploy_assume_role.json

  tags = merge(
    {
      Name        = local.config_role_name
      Environment = coalesce(try(local.account.environment, null), local.environment)
    },
    try(local.account.tags, {}),
    local.extra_tags,
  )
}

data "aws_iam_policy_document" "terraform_deploy_inline" {
  count = local.create_role ? 1 : 0

  override_policy_documents = [
    templatefile(
      "${path.module}/policies/terraform-deploy-inline-policy.json",
      {
        account_id  = local.account.account_id
        bucket_name = local.state_bucket_name
        region      = local.config_region
        role_name   = local.role_name
        table_name  = local.lock_table_name
      }
    )
  ]
}

resource "aws_iam_role_policy" "terraform_deploy_role_policy" {
  count = local.create_role ? 1 : 0

  name   = "${local.role_name}-bootstrap-minimal"
  role   = aws_iam_role.terraform_deploy_role[0].id
  policy = data.aws_iam_policy_document.terraform_deploy_inline[0].json
}

resource "aws_iam_role_policy_attachment" "terraform_deploy_role_managed" {
  count = local.create_role ? length(local.managed_policy_arns) : 0

  role       = aws_iam_role.terraform_deploy_role[0].name
  policy_arn = local.managed_policy_arns[count.index]
}

#
# IAM User for Terraform (AK/SK)
# ----------------------------------------
resource "aws_iam_user" "terraform_user" {
  count = local.create_user ? 1 : 0

  name = local.terraform_user_name
}

#
# IAM User Policy: 最小权限
# ----------------------------------------
data "aws_iam_policy_document" "terraform_user" {
  override_policy_documents = [
    templatefile(
      "${path.module}/policies/terraform-user-assume-role.json",
      {
        account_id = local.account.account_id
        role_name  = local.role_name
      }
    )
  ]
}

resource "aws_iam_user_policy" "terraform_user_policy" {
  count = local.create_user ? 1 : 0

  name   = "${local.terraform_user_name}-iac-policy"
  user   = aws_iam_user.terraform_user[0].name
  policy = data.aws_iam_policy_document.terraform_user.json
}
