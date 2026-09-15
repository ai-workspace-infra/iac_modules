locals {
  config_files = var.config_files

  account = yamldecode(
    file(local.config_files[0])
  )
}


data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.account.account_id}:root"]
    }
  }
}

module "role" {
  source = "../../modules/iam"

  name               = "app-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json

  tags = local.account.tags
}
