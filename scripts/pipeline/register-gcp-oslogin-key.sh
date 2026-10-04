#!/usr/bin/env bash
# Let the deploy jobs reach GCP Spot VMs that use OS Login.
#
# Projects under the requireOsLogin organization policy ignore metadata SSH
# keys, so the Vault deploy key must sit in the deploy principal's OS Login
# profile instead. The key expires on its own after OSLOGIN_KEY_TTL, which is
# long enough for this run's deploy jobs; it replaces a metadata key that
# never expired. The resolved POSIX user goes to GITHUB_ENV for the inventory
# renderer and is never printed.
set -euo pipefail

: "${RESOURCES_MANIFEST:?RESOURCES_MANIFEST is required}"
: "${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
: "${GITHUB_ENV:?GITHUB_ENV is required}"

ttl="${OSLOGIN_KEY_TTL:-6h}"
[[ "${ttl}" =~ ^[1-9][0-9]{0,2}[mh]$ ]] || {
  echo "::error::OSLOGIN_KEY_TTL must be minutes or hours, for example 6h." >&2
  exit 1
}

count="$(jq -er '[.spot_vms[]? | select(.enable_oslogin == true)] | length' "${RESOURCES_MANIFEST}")"
if (( count == 0 )); then
  echo "No Spot VM declares enable_oslogin; deploy jobs keep the metadata SSH key."
  exit 0
fi

: "${SSH_PUBLIC_DEPLOY_KEY:?SSH_PUBLIC_DEPLOY_KEY is required for OS Login Spot VMs}"
key_file="$(mktemp)"
trap 'rm -f "${key_file}"' EXIT
printf '%s\n' "${SSH_PUBLIC_DEPLOY_KEY}" > "${key_file}"

# OS Login acts on the active gcloud account's profile. The Selfhost job
# authenticates gcloud only through the WIF credential-file override, which
# leaves no active account ("Request for user [None]"), so register the
# credential the way setup-gcloud does. Output is discarded: it names the
# deploy principal.
if [[ -z "$(gcloud config get-value account 2>/dev/null)" ]]; then
  : "${GOOGLE_GHA_CREDS_PATH:?GOOGLE_GHA_CREDS_PATH is required to activate the WIF credential}"
  gcloud --quiet auth login --cred-file="${GOOGLE_GHA_CREDS_PATH}" >/dev/null 2>&1 || {
    echo "::error::Could not activate the GCP WIF credential for OS Login." >&2
    exit 1
  }
fi

gcloud compute os-login ssh-keys add --project="${GCP_PROJECT_ID}" --key-file="${key_file}" --ttl="${ttl}" >/dev/null
# `add` keeps the expiry of a key that is already registered, so refresh it;
# otherwise a key left by an earlier run could expire during this one.
gcloud compute os-login ssh-keys update --project="${GCP_PROJECT_ID}" --key-file="${key_file}" --ttl="${ttl}" >/dev/null

profile="$(gcloud compute os-login describe-profile --project="${GCP_PROJECT_ID}" --format=json)"
username="$(jq -er '[.posixAccounts[]? | select(.operatingSystemType == "LINUX") | .username] | first' <<<"${profile}")" || {
  echo "::error::The deploy principal has no Linux OS Login account." >&2
  exit 1
}
[[ "${username}" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || {
  echo "::error::The deploy principal's OS Login username is not a valid Linux user name." >&2
  exit 1
}
# GITHUB_ENV values are echoed in every later step's env block; mask the
# user, which carries the deploy principal's unique ID.
echo "::add-mask::${username}"
printf 'GCP_OSLOGIN_USERNAME=%s\n' "${username}" >> "${GITHUB_ENV}"
echo "Registered the deploy key with OS Login for ${count} Spot VM(s); it expires after ${ttl}."
