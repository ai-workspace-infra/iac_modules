#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# UAT Cloud Run 批量部署脚本
# 默认副本数 min-instances=0, max-instances=2
# 例外：UAT accounts 常驻 1 个实例，避免冷启动期间登录接口返回 503
# -----------------------------------------------------------------------------

GCP_PROJECT="${GCP_PROJECT_ID:?GCP_PROJECT_ID must be supplied from the validated Vault/GitOps target}"
GCP_REGION="${GCP_REGION:?GCP_REGION must be supplied from the validated Vault/GitOps target}"
GCP_ARTIFACT_REGISTRY_REGION="${GCP_ARTIFACT_REGISTRY_REGION:-${GCP_REGION}}"
IMAGE_TAG="${IMAGE_TAG:?An immutable release tag is required}"
[[ "$IMAGE_TAG" =~ ^(v|daily-build-)[0-9][A-Za-z0-9._-]*$ ]] || exit 2
DEPLOY_ENV="${DEPLOY_ENV:-uat}"

if [[ -z "${SUPABASE_CONNECT_URI:-}" ]]; then
  echo "SUPABASE_CONNECT_URI is required for Cloud Run deployment" >&2
  exit 1
fi
if [[ -z "${INTERNAL_SERVICE_TOKEN:-}" ]]; then
  echo "INTERNAL_SERVICE_TOKEN is required for Cloud Run deployment" >&2
  exit 1
fi

SERVICES=("accounts" "billing-service" "content-service")
if [[ -n "${CLOUD_RUN_SERVICE:-}" ]]; then
  SERVICES=("${CLOUD_RUN_SERVICE}")
fi

for svc in "${SERVICES[@]}"; do
  case "${svc}" in
    accounts|billing-service|content-service) ;;
    *) echo "Unsupported Cloud Run service: ${svc}" >&2; exit 2 ;;
  esac
done

echo "==> [Cloud Run] Deploying backend microservices to GCP project: ${GCP_PROJECT} (region: ${GCP_REGION}, environment: ${DEPLOY_ENV})..."

for svc in "${SERVICES[@]}"; do
  SERVICE_NAME="${DEPLOY_ENV}-${svc}"
  IMAGE_URI="${GCP_ARTIFACT_REGISTRY_REGION}-docker.pkg.dev/${GCP_PROJECT}/serverless/${svc}:${IMAGE_TAG}"

  env_vars=(
    "APP_ENV=${DEPLOY_ENV}"
    "ENV=${DEPLOY_ENV}"
    # Cloud Run uses the Supabase connection URI directly.  DATABASE_URL plus
    # DB_TLS_HOST/DB_TLS_PORT is the legacy VPS/stunnel contract and must not
    # be emitted by this deployment path.
    "SUPABASE_CONNECT_URI=${SUPABASE_CONNECT_URI}"
    "INTERNAL_SERVICE_TOKEN=${INTERNAL_SERVICE_TOKEN}"
  )
  case "${svc}" in
    accounts)
      env_vars+=(
        "CONFIG_TEMPLATE=${CONFIG_TEMPLATE:-/app/config/account.cloudrun.yaml}"
        # The PROD/UAT Supabase Session Pooler has a shared session limit. The
        # account service opens both business and admin-settings pools, so a
        # VPS-sized pool of 30 per instance can exhaust it before the revision
        # starts listening. Keep the cap deployment-scoped and overridable.
        "DB_MAX_OPEN_CONNS=${DB_MAX_OPEN_CONNS:-2}"
        "DB_MAX_IDLE_CONNS=${DB_MAX_IDLE_CONNS:-1}"
        "ROOT_BOOTSTRAP_EMAIL=${ROOT_BOOTSTRAP_EMAIL:?ROOT_BOOTSTRAP_EMAIL is required}"
        "ROOT_BOOTSTRAP_PASSWORD=${ROOT_BOOTSTRAP_PASSWORD:?ROOT_BOOTSTRAP_PASSWORD is required from Vault}"
        "AUTH_TOKEN_PUBLIC_TOKEN=${AUTH_TOKEN_PUBLIC_TOKEN:?AUTH_TOKEN_PUBLIC_TOKEN is required from Vault}"
        "AUTH_TOKEN_REFRESH_SECRET=${AUTH_TOKEN_REFRESH_SECRET:?AUTH_TOKEN_REFRESH_SECRET is required from Vault}"
        "AUTH_TOKEN_ACCESS_SECRET=${AUTH_TOKEN_ACCESS_SECRET:?AUTH_TOKEN_ACCESS_SECRET is required from Vault}"
        "GITHUB_CLIENT_ID=${GITHUB_CLIENT_ID:?GITHUB_CLIENT_ID is required from GitOps OAuth metadata}"
        "GITHUB_CLIENT_SECRET=${GITHUB_CLIENT_SECRET:?GITHUB_CLIENT_SECRET is required from Vault}"
        "OAUTH_FRONTEND_URL=${OAUTH_FRONTEND_URL:?OAUTH_FRONTEND_URL is required from GitOps OAuth metadata}"
        "OAUTH_GITHUB_REDIRECT_URL=${OAUTH_GITHUB_REDIRECT_URL:?OAUTH_GITHUB_REDIRECT_URL is required from GitOps OAuth metadata}"
        "XWORKMATE_SHARED_TENANT_DOMAIN=${XWORKMATE_SHARED_TENANT_DOMAIN:?XWORKMATE_SHARED_TENANT_DOMAIN is required}"
        "XWORKMATE_SHARED_TENANT_DOMAINS=${XWORKMATE_SHARED_TENANT_DOMAINS:-${XWORKMATE_SHARED_TENANT_DOMAIN}}"
        "XWORKMATE_BRIDGE_SERVER_URL=${XWORKMATE_BRIDGE_SERVER_URL:?XWORKMATE_BRIDGE_SERVER_URL is required}"
        "SMTP_HOST=${SMTP_HOST:-smtp.gmail.com}"
        "SMTP_PORT=${SMTP_PORT:-587}"
        # The display name carries the whole impression here. Gmail rewrites the
        # address to the authenticating account when the alias is not a verified
        # send-as, so a recipient currently sees a person's mailbox; a name that
        # reads as a system keeps the mail from looking like someone wrote it.
        "SMTP_FROM=${SMTP_FROM:-svc.plus Notifications <no-reply@xworktech.com>}"
        "STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY:-}"
        "STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET:-}"
        "STRIPE_XCONNECT_PAY_URL=${STRIPE_XCONNECT_PAY_URL:-}"
      )
      if [[ -n "${XCONNECT_OVERLAY_SIGNING_PRIVATE_KEY:-}" || -n "${XCONNECT_OVERLAY_SIGNING_KEY_ID:-}" ]]; then
        if [[ -z "${XCONNECT_OVERLAY_SIGNING_PRIVATE_KEY:-}" || -z "${XCONNECT_OVERLAY_SIGNING_KEY_ID:-}" ]]; then
          echo "XConnect Zero Signing configuration must include both the private key and key id" >&2
          exit 1
        fi
        env_vars+=(
          "XCONNECT_OVERLAY_SIGNING_PRIVATE_KEY=${XCONNECT_OVERLAY_SIGNING_PRIVATE_KEY}"
          "XCONNECT_OVERLAY_SIGNING_KEY_ID=${XCONNECT_OVERLAY_SIGNING_KEY_ID}"
        )
      else
        echo "==> [Cloud Run] XConnect Zero Signing is not configured; deploying accounts without it."
      fi
      # UAT's stable Gateway shares the host's public Caddy :443 listener.
      # Keep this deployment-only override explicit: PROD remains on the
      # standalone direct-TLS Gateway contract unless it opts in separately.
      if [[ "${DEPLOY_ENV}" == "uat" ]]; then
        env_vars+=(
          "XCONNECT_GATEWAY_XRAY_FRONTEND=${XCONNECT_GATEWAY_XRAY_FRONTEND:-caddy-unix-h2c}"
          "XCONNECT_GATEWAY_XRAY_LISTEN_SOCKET=${XCONNECT_GATEWAY_XRAY_LISTEN_SOCKET:-/run/xconnect-gateway/xray.sock}"
        )
      fi
      # Browser origins the accounts CORS middleware must accept, derived by the
      # orchestrator from the GitOps console host. Without it gin-contrib/cors
      # aborts every browser login with an empty 403 that the portal can only
      # render as a generic error.
      if [[ -n "${ALLOWED_ORIGINS:-}" ]]; then
        env_vars+=("ALLOWED_ORIGINS=${ALLOWED_ORIGINS}")
      fi
      ;;
    content-service)
      env_vars+=(
        "KNOWLEDGE_REPO_PATH=${KNOWLEDGE_REPO_PATH:?KNOWLEDGE_REPO_PATH is required from Vault}"
        "KNOWLEDGE_REPO_URL=${KNOWLEDGE_REPO_URL:-https://github.com/ai-workspace-services/knowledge.git}"
        "KNOWLEDGE_REPO_REF=${KNOWLEDGE_REPO_REF:-main}"
      )
      ;;
    billing-service)
      env_vars+=(
        "DB_MAX_OPEN_CONNS=${DB_MAX_OPEN_CONNS:-2}"
        "DB_MAX_IDLE_CONNS=${DB_MAX_IDLE_CONNS:-1}"
        "BILLING_INGEST_MODE=${BILLING_INGEST_MODE:-push}"
      )
      ;;
  esac
  env_delimiter=""
  for candidate in '|' ';' '%' '~' '^' '+' ':'; do
    candidate_used=false
    for env_var in "${env_vars[@]}"; do
      if [[ "${env_var}" == *"${candidate}"* ]]; then
        candidate_used=true
        break
      fi
    done
    if [[ "${candidate_used}" == false ]]; then
      env_delimiter="${candidate}"
      break
    fi
  done
  if [[ -z "${env_delimiter}" ]]; then
    echo "Unable to choose a safe gcloud env-var delimiter" >&2
    exit 1
  fi
  env_vars_joined="$(IFS="${env_delimiter}"; printf '%s' "${env_vars[*]}")"

  secret_flags=()
  if [[ "${svc}" == "accounts" ]]; then
    if gcloud secrets describe smtp-username --project="${GCP_PROJECT}" --quiet >/dev/null 2>&1 && \
       gcloud secrets describe smtp-password --project="${GCP_PROJECT}" --quiet >/dev/null 2>&1; then
      echo "==> [Cloud Run] Binding Secret Manager SMTP credentials (smtp-username, smtp-password)..."
      secret_flags+=("--set-secrets=SMTP_USERNAME=smtp-username:latest,SMTP_PASSWORD=smtp-password:latest")
    else
      echo "==> [Cloud Run] SMTP secrets not present in Secret Manager; skipping secret bindings."
    fi
  fi

  # accounts serves the console's /api/auth/* calls. Scaled to zero it is shut
  # down once idle, and the next sign-in pays a ~35s cold start: every auth
  # request landing in that window is answered 503, which the console surfaces
  # as "登录失败 (503 / authentication_failed)". Keep one instance warm on that
  # path. Every other service, and every other environment, still scales to
  # zero unless CLOUD_RUN_MIN_INSTANCES overrides it -- this script also
  # deploys prod, where the idle cost is not wanted by default.
  if [[ "${svc}" == "accounts" && "${DEPLOY_ENV}" == "uat" ]]; then
    min_instances="${CLOUD_RUN_MIN_INSTANCES:-1}"
  else
    min_instances="${CLOUD_RUN_MIN_INSTANCES:-0}"
  fi

  echo "==> [Cloud Run] Deploying ${SERVICE_NAME} (min=${min_instances}, max=2)..."

  # Deploy and inject the service-specific runtime contract.
  # Organization policy blocks the allUsers IAM member. Cloudflare Workers
  # reach the public edge after routing, so disable the Cloud Run Invoker IAM
  # check instead of writing an allUsers binding. This keeps redeploys
  # idempotent across projects with iam.allowedPolicyMemberDomains enforced.
  gcloud run deploy "${SERVICE_NAME}" \
    --project="${GCP_PROJECT}" \
    --region="${GCP_REGION}" \
    --image="${IMAGE_URI}" \
    --platform=managed \
    --no-invoker-iam-check \
    --min-instances="${min_instances}" \
    --max-instances=2 \
    --cpu=1 \
    --memory=512Mi \
    --set-env-vars="^${env_delimiter}^${env_vars_joined}" \
    "${secret_flags[@]}" \
    --quiet
done

echo "==> [Cloud Run] Backend microservices deployment finished."
