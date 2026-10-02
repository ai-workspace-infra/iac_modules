locals {
  issuer_host = trimsuffix(trimprefix(var.oidc_url, "https://"), "/")
}

resource "aws_iam_openid_connect_provider" "this" {
  url             = var.oidc_url
  client_id_list  = [var.client_id]
  thumbprint_list = var.thumbprint_list
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    sid     = "AllowExactOidcSubject"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.this.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.issuer_host}:aud"
      values   = [var.client_id]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.issuer_host}:sub"
      values   = [var.subject]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = var.role_name
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  description        = "OIDC workload role; attach least-privilege permissions outside this module."
}
