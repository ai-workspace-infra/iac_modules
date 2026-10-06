#!/usr/bin/env bash
# IaC-owned adapter for an approved canonical PROD CMDB. No host/DB execution.
set -euo pipefail
phase="${1:-}"
[[ "$phase" == open || "$phase" == close ]] || exit 2
: "${CMDB_FILE:?trusted resource CMDB is required}"
: "${EXPECTED_CMDB_SHA256:?reviewed CMDB checksum is required}"
: "${ACCESS_DIR:?private one-run directory is required}"
: "${GITHUB_RUN_ID:?GitHub runner is required}"
: "${GITHUB_RUN_ATTEMPT:?GitHub attempt is required}"
: "${RUNNER_TEMP:?GitHub private runner directory is required}"
[[ "$GITHUB_RUN_ID" =~ ^[1-9][0-9]*$ && "$GITHUB_RUN_ATTEMPT" =~ ^[1-9][0-9]*$ ]]
[[ "$ACCESS_DIR" == "$RUNNER_TEMP/prod-native-access-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" ]] || {
  echo 'Ephemeral access directory is outside this run contract.' >&2; exit 1;
}
[[ "$EXPECTED_CMDB_SHA256" =~ ^[0-9a-f]{64}$ ]]
actual="$(sha256sum "$CMDB_FILE" | cut -d ' ' -f 1)"
[[ "$actual" == "$EXPECTED_CMDB_SHA256" ]] || { echo 'Approved resource CMDB checksum differs.' >&2; exit 1; }
jq -e '
 .environment == "prod" and .project_id == "open-platform-prod" and
 .deploy_account == "github-actions-prod@open-platform-prod.iam.gserviceaccount.com" and
 .["web-saas-prod"].provider == "gcp-cloud" and
 .["web-saas-prod"].zone == "asia-east1-a" and
 .["web-saas-prod"].provisioning_model == "STANDARD" and
 (.["web-saas-prod"].groups | index("web_saas") != null) and
 .["web-saas-prod"].data_disk.id == "projects/open-platform-prod/zones/asia-east1-a/disks/web-saas-prod-data" and
 .["web-saas-prod"].data_disk.mount_path == "/data"
' "$CMDB_FILE" >/dev/null || { echo 'Canonical PROD resource identity differs.' >&2; exit 1; }

: "${GOOGLE_GHA_CREDS_PATH:?exact GitHub WIF credential is required}"
principal='github-actions-prod@open-platform-prod.iam.gserviceaccount.com'
expected_url="https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${principal}:generateAccessToken"
jq -e --arg url "$expected_url" '.type == "external_account" and .service_account_impersonation_url == $url' \
  "$GOOGLE_GHA_CREDS_PATH" >/dev/null || { echo 'GitHub WIF principal differs.' >&2; exit 1; }
gcloud --quiet auth login --cred-file="$GOOGLE_GHA_CREDS_PATH" >/dev/null 2>&1
export GCP_PROJECT_ID=open-platform-prod GCP_ZONE=asia-east1-a GCP_INSTANCE=web-saas-prod
export GCP_NETWORK=web-saas-prod-gcp ENSURE_RUNNING=false OSLOGIN_KEY_TTL=45m
export GCP_OSLOGIN_DEPLOY_ACCOUNT="$principal"
export ACCESS_RULE_NAME="web-saas-prod-ci-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$phase" == open ]]; then
  firewall="$(gcloud compute firewall-rules describe web-saas-prod-gcp-spot-ssh --project="$GCP_PROJECT_ID" --format=json)"
  jq -e '
    .name == "web-saas-prod-gcp-spot-ssh" and .direction == "INGRESS" and (.disabled // false) == false and
    .network == "https://www.googleapis.com/compute/v1/projects/open-platform-prod/global/networks/web-saas-prod-gcp" and
    (.sourceRanges | sort) == (["10.73.0.0/25", "10.73.0.128/25"] | sort) and
    .targetTags == ["web-saas-ssh"] and
    (.allowed | length == 1) and .allowed[0].IPProtocol == "tcp" and .allowed[0].ports == ["22"] and
    ((.sourceTags // []) | length == 0) and ((.sourceServiceAccounts // []) | length == 0)
  ' <<< "$firewall" >/dev/null || { echo 'Permanent PROD SSH firewall is not private; refusing CI access.' >&2; exit 1; }
  echo 'Verified live permanent SSH source ranges equal the declared private subnet; no public default remains.'
  # Read live cloud facts before granting one-run access. Never start or recreate
  # an instance on the strength of a stale artifact.
  facts="$(gcloud compute instances describe "$GCP_INSTANCE" --project="$GCP_PROJECT_ID" --zone="$GCP_ZONE" --format=json)"
  reviewed_ip="$(jq -er '.["web-saas-prod"].ip' "$CMDB_FILE")"
  reviewed_user="$(jq -er '.["web-saas-prod"].ansible_user' "$CMDB_FILE")"
  jq -e --arg ip "$reviewed_ip" '
    .name == "web-saas-prod" and .status == "RUNNING" and .deletionProtection == true and
    .scheduling.provisioningModel == "STANDARD" and
    (.metadata.items | any(.key == "enable-oslogin" and .value == "TRUE")) and
    (.networkInterfaces | length == 1) and
    .networkInterfaces[0].network == "https://www.googleapis.com/compute/v1/projects/open-platform-prod/global/networks/web-saas-prod-gcp" and
    (.networkInterfaces[0].accessConfigs | any(.natIP == $ip)) and
    (.disks | any(.deviceName == "web-saas-prod-data" and .autoDelete == false and
      .source == "https://www.googleapis.com/compute/v1/projects/open-platform-prod/zones/asia-east1-a/disks/web-saas-prod-data"))
  ' <<< "$facts" >/dev/null || { echo 'Live PROD VM/disk differs from the accepted resource contract.' >&2; exit 1; }
fi
bash "$script_dir/gcp-temporary-ssh-access.sh" "$phase"
if [[ "$phase" == open ]]; then
  # Returned access is a runner file, never an artifact or a new CMDB.
  jq -e --arg ip "$reviewed_ip" --arg user "$reviewed_user" '.target_ip == $ip and .ssh_user == $user and .instance == "web-saas-prod"' "$ACCESS_DIR/access.json" >/dev/null || {
    bash "$script_dir/gcp-temporary-ssh-access.sh" close
    echo 'Ephemeral target discovery differs; access revoked.' >&2; exit 1;
  }
fi
