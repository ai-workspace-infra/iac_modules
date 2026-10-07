#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# UAT Cloudflare Worker 网关部署脚本
# -----------------------------------------------------------------------------

WORKER_DIR="${WORKER_DIR:?WORKER_DIR must point to a checked-out edge-gateway repository}"
EDGE_GATEWAY_CONFIG_FILE="${EDGE_GATEWAY_CONFIG_FILE:-${CLOUDFLARE_BOUNDARY_CONFIG:-}}"
export EDGE_GATEWAY_CONFIG_FILE

case "${EDGE_GATEWAY_BOUNDARY:-}" in
  auth|admin|core) ;;
  *)
    echo "EDGE_GATEWAY_BOUNDARY must be auth, admin, or core" >&2
    exit 2
    ;;
esac

echo "==> [Cloudflare Worker UAT] Deploying edge-gateway boundary: ${EDGE_GATEWAY_BOUNDARY}..."

test -d "${WORKER_DIR}"
pushd "${WORKER_DIR}" > /dev/null
corepack enable 2>/dev/null || true
npm ci
test -x .github/scripts/deploy_boundary.sh
bash .github/scripts/deploy_boundary.sh "${EDGE_GATEWAY_BOUNDARY}"
popd > /dev/null

echo "==> [Cloudflare Worker UAT] Edge-gateway ${EDGE_GATEWAY_BOUNDARY} deployment finished."
