# Tested with Terraform 1.16.0. All runs use plan and a mock; no AWS credentials or apply.
mock_provider "aws" {
  override_during = plan
  mock_resource "aws_iam_openid_connect_provider" {
    defaults = { arn = "arn:aws:iam::123456789012:oidc-provider/idp.example.test" }
  }
}

variables {
  oidc_url        = "https://idp.example.test/"
  client_id       = "test-audience"
  subject         = "exact-test-subject"
  role_name       = "test-oidc-role"
  thumbprint_list = ["0123456789012345678901234567890123456789"]
}

run "exact_trust" {
  command = plan
  assert {
    condition     = toset(aws_iam_openid_connect_provider.this.client_id_list) == toset([var.client_id])
    error_message = "Provider must accept only the configured audience."
  }
  assert {
    condition     = length(data.aws_iam_policy_document.assume_role.statement) == 1 && data.aws_iam_policy_document.assume_role.statement[0].actions == toset(["sts:AssumeRoleWithWebIdentity"])
    error_message = "Trust must contain only web identity assumption."
  }
  assert {
    condition = length(data.aws_iam_policy_document.assume_role.statement[0].condition) == 2 && alltrue([
      for c in data.aws_iam_policy_document.assume_role.statement[0].condition :
      c.test == "StringEquals" && (
        (c.variable == "idp.example.test:aud" && c.values == tolist([var.client_id])) ||
        (c.variable == "idp.example.test:sub" && c.values == tolist([var.subject]))
      )
    ])
    error_message = "Trust must match exact issuer/audience/subject, without wildcards."
  }
  assert {
    condition     = length(data.aws_iam_policy_document.assume_role.statement[0].principals) == 1 && alltrue([for p in data.aws_iam_policy_document.assume_role.statement[0].principals : p.type == "Federated" && p.identifiers == toset([aws_iam_openid_connect_provider.this.arn])])
    error_message = "Trust must use only this federated provider."
  }
}

run "reject_http" {
  command = plan
  variables { oidc_url = "http://idp.example.test" }
  expect_failures = [var.oidc_url]
}
run "reject_empty_audience" {
  command = plan
  variables { client_id = " " }
  expect_failures = [var.client_id]
}
run "reject_wildcard_subject" {
  command = plan
  variables { subject = "prefix-*" }
  expect_failures = [var.subject]
}
run "reject_empty_subject" {
  command = plan
  variables { subject = " " }
  expect_failures = [var.subject]
}
run "reject_invalid_thumbprint" {
  command = plan
  variables { thumbprint_list = ["not-a-thumbprint"] }
  expect_failures = [var.thumbprint_list]
}
run "reject_empty_thumbprints" {
  command = plan
  variables { thumbprint_list = [] }
  expect_failures = [var.thumbprint_list]
}
run "reject_role_name" {
  command = plan
  variables { role_name = "invalid/role" }
  expect_failures = [var.role_name]
}
