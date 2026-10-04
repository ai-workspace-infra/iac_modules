#!/bin/bash
terraform init -input=false \
  -backend-config="bucket=${TF_STATE_BUCKET}" \
  -backend-config="key=${ENV_STEPS_ROUTE_OUTPUTS_STATE_KEY}" \
  -backend-config="access_key=${TF_STATE_ACCESS_KEY}" \
  -backend-config="secret_key=${TF_STATE_SECRET_KEY}" \
  -backend-config="region=${TF_STATE_REGION}" \
  -backend-config="skip_credentials_validation=true" \
  -backend-config="skip_metadata_api_check=true" \
  -backend-config="skip_region_validation=true" \
  -backend-config="use_path_style=true" \
  -backend-config="use_lockfile=true"
