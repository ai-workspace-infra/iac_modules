#!/usr/bin/env bash
# Grafana is the baseline monitoring path and the fallback when Guance is disabled.
# This check is deliberately independent of Guance: it reads no Guance variable and needs no
# Vault credential, so it keeps working with every Guance write path turned off.
#   grafana-fallback-check.sh [--url BASE]   (default https://observability.svc.plus/grafana)
set -euo pipefail
set +x
base="${GRAFANA_BASE_URL:-https://observability.svc.plus/grafana}"
if [[ "${1:-}" == --url ]]; then base="${2:?}"; fi
[[ "$base" =~ ^https?://[A-Za-z0-9.:-]+(/[A-Za-z0-9._/-]*)?$ ]] || { printf 'Invalid Grafana URL.\n' >&2; exit 2; }
command -v curl >/dev/null && command -v jq >/dev/null || { printf 'curl and jq are required.\n' >&2; exit 2; }
body="$(curl -fsS --max-time 20 --retry 2 --retry-delay 2 "${base%/}/api/health")" \
  || { printf 'FAIL: Grafana health endpoint unreachable.\n' >&2; exit 1; }
if ! jq -e '.database == "ok"' >/dev/null 2>&1 <<<"$body"; then
  printf 'FAIL: Grafana reports an unhealthy database.\n' >&2
  exit 1
fi
printf 'OK: Grafana healthy (version %s)\n' "$(jq -r '.version // "unknown"' <<<"$body")"
