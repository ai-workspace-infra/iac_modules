#!/usr/bin/env python3
"""
渲染 Terraform S3 backend 配置文件（backend.tf）。

用法：
  TF_STATE_ENDPOINT=https://... python3 render_backend_tf.py [output_path]

默认输出到当前目录的 backend.tf（在 terraform working-directory 里执行）。
"""
import os
import sys

endpoint = os.environ.get("TF_STATE_ENDPOINT", "")
if not endpoint:
    print("ERROR: TF_STATE_ENDPOINT is not set", file=sys.stderr)
    sys.exit(1)

output = sys.argv[1] if len(sys.argv) > 1 else "backend.tf"

content = f"""\
terraform {{
    backend "s3" {{
    endpoints                   = {{ s3 = "{endpoint}" }}
    region                      = "us-east-1"
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
    use_path_style              = true
  }}
}}
"""

with open(output, "w") as f:
    f.write(content)

print(f"backend.tf written to {output}")
print(f"  endpoint = {endpoint[:40]}...")
print("  region   = us-east-1")
