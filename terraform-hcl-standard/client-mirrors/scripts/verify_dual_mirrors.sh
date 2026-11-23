#!/usr/bin/env bash
# End-to-end smoke verification for dual mirrors (dl.svc.plus + cn-dl.svc.plus).
# With --upload-from-vault, reads minimal storage credentials from Vault KV v2
# into process env only, uploads releases/_health/probe.json to both buckets, and
# verifies HTTPS 200 + CORS headers over the public mirror domains.
set -euo pipefail
set +x

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
r2_domain='dl.svc.plus'
cn_domain='cn-dl.svc.plus'
probe_path='releases/_health/probe.json'
origin='https://console.svc.plus'
upload=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --r2-domain) r2_domain="${2:?}"; shift 2 ;;
    --cn-domain) cn_domain="${2:?}"; shift 2 ;;
    --probe-path) probe_path="${2:?}"; shift 2 ;;
    --origin) origin="${2:?}"; shift 2 ;;
    --upload-from-vault) upload=true; shift ;;
    *) printf 'Usage: verify_dual_mirrors.sh [--r2-domain HOST] [--cn-domain HOST] [--probe-path PATH] [--origin URL] [--upload-from-vault]\n' >&2; exit 2 ;;
  esac
done

extra_args=()
if [[ "$upload" == true ]]; then
  command -v vault >/dev/null || { printf 'vault CLI is required for --upload-from-vault.\n' >&2; exit 1; }
  R2_ENDPOINT="$(vault kv get -mount=kv -field=endpoint prod/platform/storage/cloudflare-r2)"
  R2_BUCKET="$(vault kv get -mount=kv -field=bucket prod/platform/storage/cloudflare-r2)"
  R2_ACCESS_KEY_ID="$(vault kv get -mount=kv -field=access_key_id prod/platform/storage/cloudflare-r2)"
  R2_SECRET_ACCESS_KEY="$(vault kv get -mount=kv -field=secret_access_key prod/platform/storage/cloudflare-r2)"
  OSS_ENDPOINT="$(vault kv get -mount=kv -field=endpoint prod/platform/storage/aliyun-oss)"
  OSS_BUCKET="$(vault kv get -mount=kv -field=bucket prod/platform/storage/aliyun-oss)"
  OSS_ACCESS_KEY_ID="$(vault kv get -mount=kv -field=access_key_id prod/platform/storage/aliyun-oss)"
  OSS_ACCESS_KEY_SECRET="$(vault kv get -mount=kv -field=access_key_secret prod/platform/storage/aliyun-oss)"
  export R2_ENDPOINT R2_BUCKET R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY
  export OSS_ENDPOINT OSS_BUCKET OSS_ACCESS_KEY_ID OSS_ACCESS_KEY_SECRET
  extra_args+=(--upload)
fi

python3 "$here/probe_dual_mirrors.py" \
  --r2-domain "$r2_domain" \
  --cn-domain "$cn_domain" \
  --probe-path "$probe_path" \
  --origin "$origin" \
  "${extra_args[@]}"
