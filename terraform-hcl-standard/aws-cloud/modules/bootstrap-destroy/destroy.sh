#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH=${CONFIG_PATH:?Set CONFIG_PATH to the GitOps bootstrap declaration before teardown}

read TERRAFORM_USER ROLE_NAME STATE_BUCKET LOCK_TABLE AWS_REGION ACCOUNT_ID <<< "$(python - <<'PY'
import yaml
import os

config_path = os.environ['CONFIG_PATH']

with open(config_path, 'r') as f:
    cfg = yaml.safe_load(f)

print(
    cfg['iam']['terraform_user_name'],
    cfg['iam']['role_name'],
    cfg['state']['bucket_name'],
    cfg['state']['dynamodb_table_name'],
    cfg['region'],
    cfg['account_id'],
)
PY
)"

export AWS_DEFAULT_REGION="$AWS_REGION"
echo "Cleaning bootstrap resources in $AWS_REGION for account $ACCOUNT_ID"

echo "Deleting Terraform automation user: $TERRAFORM_USER"
if aws iam get-user --user-name "$TERRAFORM_USER" >/dev/null 2>&1; then
  access_keys=$(aws iam list-access-keys --user-name "$TERRAFORM_USER" --query 'AccessKeyMetadata[].AccessKeyId' --output text)
  if [ -n "$access_keys" ]; then
    for key in $access_keys; do
      aws iam delete-access-key --user-name "$TERRAFORM_USER" --access-key-id "$key" || true
    done
  fi

  aws iam delete-user-policy --user-name "$TERRAFORM_USER" --policy-name "${TERRAFORM_USER}-iac-policy" || true
  aws iam delete-user --user-name "$TERRAFORM_USER" || true
else
  echo "User $TERRAFORM_USER not found; skipping"
fi

echo "Deleting Terraform deploy role: $ROLE_NAME"
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam delete-role-policy --role-name "$ROLE_NAME" --policy-name "${ROLE_NAME}-bootstrap-minimal" || true
  aws iam delete-role --role-name "$ROLE_NAME" || true
else
  echo "Role $ROLE_NAME not found; skipping"
fi

echo "Deleting DynamoDB lock table: $LOCK_TABLE"
if aws dynamodb describe-table --table-name "$LOCK_TABLE" >/dev/null 2>&1; then
  aws dynamodb delete-table --table-name "$LOCK_TABLE" || true
  aws dynamodb wait table-not-exists --table-name "$LOCK_TABLE" || true
else
  echo "Lock table $LOCK_TABLE not found; skipping"
fi

echo "Deleting state bucket: $STATE_BUCKET"
if aws s3api head-bucket --bucket "$STATE_BUCKET" >/dev/null 2>&1; then
  aws s3 rb "s3://$STATE_BUCKET" --force || true
else
  echo "Bucket $STATE_BUCKET not found; skipping"
fi

echo "Bootstrap teardown completed"
