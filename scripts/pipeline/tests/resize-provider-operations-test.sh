#!/usr/bin/env bash
set -euo pipefail

pipeline_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
workdir="$(mktemp -d)"
trap 'rm -rf -- "${workdir}"' EXIT
export CALLS_FILE="${workdir}/calls"

curl() {
  local arg
  for arg in "$@"; do
    case "${arg}" in
      *'dns_records?type=A'*) printf '{"result":[{"id":"record-1"}]}\n'; return 0 ;;
      *'/dns_records/record-1') printf '{"success":true}\n'; return 0 ;;
      *'/instances/source-1') printf 'DELETE\n' >> "${CALLS_FILE}"; return 0 ;;
    esac
  done
  return 1
}
export -f curl

export CLOUDFLARE_API_TOKEN=fixture CLOUDFLARE_ZONE_ID=zone-1
export TARGET_DOMAIN=example.test REPLACEMENT_IP=192.0.2.2
bash "${pipeline_dir}/cloudflare-dns-cutover.sh"

export VULTR_API_KEY=fixture INSTANCE_ID=source-1
if bash "${pipeline_dir}/vultr-destroy-source-instance.sh" >/dev/null 2>&1; then
  echo 'destroy must require explicit confirmation' >&2
  exit 1
fi
test ! -e "${CALLS_FILE}"
CONFIRM_DESTROY=true bash "${pipeline_dir}/vultr-destroy-source-instance.sh" >/dev/null
test "$(cat "${CALLS_FILE}")" = DELETE
echo 'resize-provider-operations-test: PASS'
