#!/bin/bash
CONFIG_FILES="gitops/${PROJECT}/${DEPLOY_ENV}/${CLOUD_PROVIDER}/account/bootstrap.yaml"
export ACCOUNT_FILE="$CONFIG_FILES"
python - <<'PY'
import os
import sys
from pathlib import Path
utils_dir = Path("iac_modules/terraform-hcl-standard/utils").resolve()
sys.path.insert(0, str(utils_dir))
from config_loader import load_account_credentials
try:
    region, role_arn = load_account_credentials(os.environ["ACCOUNT_FILE"])
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as handle:
        handle.write(f"AWS_REGION={region}\n")
        handle.write(f"AWS_ROLE_ARN={role_arn}\n")
except Exception as e:
    print(f"Warning: Failed to load dynamic AWS config: {e}")
    sys.exit(0)
PY
