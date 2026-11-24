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
r2_kv_path='prod/platform/storage/cloudflare-r2'
oss_kv_path='prod/platform/storage/aliyun-oss'
upload=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --r2-domain) r2_domain="${2:?}"; shift 2 ;;
    --cn-domain) cn_domain="${2:?}"; shift 2 ;;
    --probe-path) probe_path="${2:?}"; shift 2 ;;
    --origin) origin="${2:?}"; shift 2 ;;
    --r2-kv-path) r2_kv_path="${2:?}"; shift 2 ;;
    --oss-kv-path) oss_kv_path="${2:?}"; shift 2 ;;
    --upload-from-vault) upload=true; shift ;;
    *) printf 'Usage: verify_dual_mirrors.sh [--r2-domain HOST] [--cn-domain HOST] [--probe-path PATH] [--origin URL] [--r2-kv-path PATH] [--oss-kv-path PATH] [--upload-from-vault]\n' >&2; exit 2 ;;
  esac
done

r2_kv_path="${r2_kv_path#kv/}"
r2_kv_path="${r2_kv_path#/}"
oss_kv_path="${oss_kv_path#kv/}"
oss_kv_path="${oss_kv_path#/}"

extra_args=()
if [[ "$upload" == true ]]; then
  command -v vault >/dev/null || { printf 'vault CLI is required for --upload-from-vault.\n' >&2; exit 1; }
  R2_ENDPOINT="$(vault kv get -mount=kv -field=endpoint "$r2_kv_path")"
  R2_BUCKET="$(vault kv get -mount=kv -field=bucket "$r2_kv_path")"
  R2_ACCESS_KEY_ID="$(vault kv get -mount=kv -field=access_key_id "$r2_kv_path")"
  R2_SECRET_ACCESS_KEY="$(vault kv get -mount=kv -field=secret_access_key "$r2_kv_path")"
  OSS_ENDPOINT="$(vault kv get -mount=kv -field=endpoint "$oss_kv_path")"
  OSS_BUCKET="$(vault kv get -mount=kv -field=bucket "$oss_kv_path")"
  OSS_ACCESS_KEY_ID="$(vault kv get -mount=kv -field=access_key_id "$oss_kv_path")"
  OSS_ACCESS_KEY_SECRET="$(vault kv get -mount=kv -field=access_key_secret "$oss_kv_path")"
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
