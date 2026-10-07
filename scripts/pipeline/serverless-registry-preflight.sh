#!/usr/bin/env bash
set -euo pipefail
: "${GCP_PROJECT_ID:?}" "${GCP_REGION:?}" "${CLOUD_RUN_SERVICE:?}"
[[ "$GCP_PROJECT_ID" =~ ^[a-z][a-z0-9-]{4,61}[a-z0-9]$ && "$GCP_REGION" =~ ^[a-z]+-[a-z]+[0-9]$ ]] || exit 2
case "$CLOUD_RUN_SERVICE" in accounts|billing-service|content-service) ;; *) exit 2 ;; esac
gcloud artifacts repositories describe serverless --location="$GCP_REGION" \
  --project="$GCP_PROJECT_ID" --format='value(name)' >/dev/null 2>&1
echo 'IaC verified the selected serverless Artifact Registry repository.'
