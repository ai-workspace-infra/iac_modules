#!/usr/bin/env bash
# Short-lived SSH access from a CI runner to one GCP VM that uses OS Login.
#
#   gcp-temporary-ssh-access.sh open    reconcile the VM to RUNNING, read its
#                                       public IPv4 and network tags, register
#                                       a one-run ed25519 key with OS Login
#                                       (with a TTL) and allow tcp:22 from this
#                                       runner's /32 to the VM's tags only
#   gcp-temporary-ssh-access.sh close   delete and re-check the firewall rule,
#                                       revoke the key, remove ACCESS_DIR
#
# open writes the target facts to ${ACCESS_DIR}/access.json (and GITHUB_OUTPUT)
# for the caller's inventory. It never prints the private key, and masks the
# OS Login user, which carries the deploy principal's unique ID. A failed open
# rolls back what it created; close is idempotent, keeps going after a failed
# step and exits non-zero if any revocation failed. The caller runs close in an
# always()/EXIT path with the same ACCESS_RULE_NAME and ACCESS_DIR.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/require-env.sh
. "${script_dir}/lib/require-env.sh"

name_re='^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$'

common_inputs() {
  require_env GCP_PROJECT_ID ACCESS_RULE_NAME ACCESS_DIR
  [[ "${GCP_PROJECT_ID}" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || { echo '::error::GCP_PROJECT_ID is not a project ID.' >&2; exit 2; }
  [[ "${ACCESS_RULE_NAME}" =~ ${name_re} ]] || { echo '::error::ACCESS_RULE_NAME is not a valid firewall rule name.' >&2; exit 2; }
  [[ "${ACCESS_DIR}" == /?*/* && "${ACCESS_DIR}" != *..* ]] || { echo '::error::ACCESS_DIR must be a private absolute directory.' >&2; exit 2; }
}

# present | absent | unknown. A list error is "unknown", never "absent": an
# API or permission failure must not read as a revoked rule.
rule_state() {
  local names
  names="$(gcloud compute firewall-rules list --project="${GCP_PROJECT_ID}" \
    --filter="name=(${ACCESS_RULE_NAME})" --format='value(name)' 2>/dev/null)" || { echo unknown; return; }
  if grep -Fxq -- "${ACCESS_RULE_NAME}" <<<"${names}"; then echo present; else echo absent; fi
}

close_access() {
  local result=0 state
  state="$(rule_state)"
  if [[ "${state}" != absent ]]; then
    gcloud compute firewall-rules delete "${ACCESS_RULE_NAME}" --project="${GCP_PROJECT_ID}" --quiet >/dev/null 2>&1 || true
    state="$(rule_state)"
  fi
  if [[ "${state}" != absent ]]; then
    echo "::error::Temporary SSH firewall rule ${ACCESS_RULE_NAME} is ${state/present/still present}." >&2
    result=1
  fi
  if [[ -f "${ACCESS_DIR}/id_ed25519.pub" ]]; then
    gcloud compute os-login ssh-keys remove --project="${GCP_PROJECT_ID}" \
      --key-file="${ACCESS_DIR}/id_ed25519.pub" >/dev/null || {
      echo '::error::The temporary OS Login key could not be revoked; it still expires at its TTL.' >&2
      result=1
    }
  fi
  rm -rf -- "${ACCESS_DIR}" || result=1
  return "${result}"
}

open_access() {
  require_env GCP_ZONE GCP_INSTANCE GCP_NETWORK
  [[ "${GCP_INSTANCE}" =~ ${name_re} && "${GCP_ZONE}" =~ ^[a-z]+-[a-z]+[0-9]-[a-z]$ && "${GCP_NETWORK}" =~ ${name_re} ]] || {
    echo '::error::GCP_INSTANCE, GCP_ZONE or GCP_NETWORK is invalid.' >&2; exit 2;
  }
  local ttl="${OSLOGIN_KEY_TTL:-20m}"
  [[ "${ttl}" =~ ^([1-9]|[1-9][0-9]|1[01][0-9]|120)m$ ]] || {
    echo '::error::OSLOGIN_KEY_TTL must be 1m to 120m.' >&2; exit 2;
  }
  [[ ! -e "${ACCESS_DIR}" ]] || { echo '::error::ACCESS_DIR already exists; refusing to reuse another run access.' >&2; exit 2; }
  case "$(rule_state)" in
    absent) ;;
    present) echo "::error::Firewall rule ${ACCESS_RULE_NAME} already exists; refusing to adopt it." >&2; exit 1 ;;
    *) echo '::error::Cannot list firewall rules; refusing to open access.' >&2; exit 1 ;;
  esac

  # From here on anything created is rolled back if open does not finish.
  trap 'status=$?; trap - EXIT; if (( status != 0 )); then echo "::error::Opening temporary SSH access failed; rolling back." >&2; close_access || true; fi; exit "${status}"' EXIT
  install -d -m 700 "${ACCESS_DIR}"

  if [[ "${ENSURE_RUNNING:-true}" == true ]]; then
    python3 "${script_dir}/ensure-gcp-vm-running.py" --instance "${GCP_INSTANCE}" --zone "${GCP_ZONE}" --project "${GCP_PROJECT_ID}"
  fi
  local instance status target_ip tags
  instance="$(gcloud compute instances describe "${GCP_INSTANCE}" --project="${GCP_PROJECT_ID}" --zone="${GCP_ZONE}" --format=json)"
  status="$(jq -r '.status // empty' <<<"${instance}")"
  [[ "${status}" == RUNNING ]] || { echo "::error::${GCP_INSTANCE} is ${status:-unknown}, not RUNNING." >&2; exit 1; }
  target_ip="$(jq -r '[.networkInterfaces[]?.accessConfigs[]?.natIP // empty] | first // empty' <<<"${instance}")"
  tags="${TARGET_TAGS:-$(jq -r '(.tags.items // []) | join(",")' <<<"${instance}")}"
  python3 - "${target_ip}" "${tags}" <<'PY'
import ipaddress, re, sys
try:
    address = ipaddress.IPv4Address(sys.argv[1])
except ValueError:
    raise SystemExit("::error::the VM has no public IPv4 address")
if not address.is_global:
    raise SystemExit("::error::the VM has no public IPv4 address")
tags = sys.argv[2].split(",")
if not sys.argv[2] or any(not re.fullmatch(r"[a-z]([-a-z0-9]{0,61}[a-z0-9])?", tag) for tag in tags):
    raise SystemExit("::error::the VM has no valid network tags to scope the firewall rule")
PY

  local source_ip
  source_ip="${SOURCE_IP:-$(curl --fail --silent --show-error --retry 3 --connect-timeout 5 --max-time 15 https://api.ipify.org)}"
  python3 - "${source_ip}" <<'PY'
import ipaddress, sys
try:
    public = ipaddress.IPv4Address(sys.argv[1]).is_global
except ValueError:
    public = False
if not public:
    raise SystemExit("::error::the runner egress address is not a public IPv4 address")
PY

  ssh-keygen -q -t ed25519 -N '' -C "ci-${ACCESS_RULE_NAME}" -f "${ACCESS_DIR}/id_ed25519"
  gcloud compute os-login ssh-keys add --project="${GCP_PROJECT_ID}" \
    --key-file="${ACCESS_DIR}/id_ed25519.pub" --ttl="${ttl}" >/dev/null
  local profile ssh_user
  profile="$(gcloud compute os-login describe-profile --project="${GCP_PROJECT_ID}" --format=json)"
  ssh_user="$(jq -r '[.posixAccounts[]? | select(.operatingSystemType == "LINUX") | .username] | first // empty' <<<"${profile}")"
  [[ "${ssh_user}" =~ ^[a-z_][a-z0-9_-]{0,31}\$?$ ]] || { echo '::error::OS Login returned no valid Linux user.' >&2; exit 1; }
  [[ -z "${GITHUB_ACTIONS:-}" ]] || echo "::add-mask::${ssh_user}"

  gcloud compute firewall-rules create "${ACCESS_RULE_NAME}" --project="${GCP_PROJECT_ID}" \
    --network="${GCP_NETWORK}" --direction=INGRESS --priority=1000 --action=ALLOW --rules=tcp:22 \
    --source-ranges="${source_ip}/32" --target-tags="${tags}" \
    --description="Temporary CI SSH access to ${GCP_INSTANCE}" --quiet >/dev/null

  jq -n --arg instance "${GCP_INSTANCE}" --arg project "${GCP_PROJECT_ID}" --arg zone "${GCP_ZONE}" \
    --arg ip "${target_ip}" --arg tags "${tags}" --arg user "${ssh_user}" --arg dir "${ACCESS_DIR}" \
    --arg rule "${ACCESS_RULE_NAME}" --arg source "${source_ip}/32" --arg ttl "${ttl}" \
    '{instance:$instance, project:$project, zone:$zone, target_ip:$ip, target_tags:($tags|split(",")),
      ssh_user:$user, private_key:($dir + "/id_ed25519"), known_hosts:($dir + "/known_hosts"),
      firewall_rule:$rule, source_range:$source, oslogin_key_ttl:$ttl}' > "${ACCESS_DIR}/access.json"
  chmod 600 "${ACCESS_DIR}/access.json"
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    {
      echo "access_file=${ACCESS_DIR}/access.json"
      echo "target_ip=${target_ip}"
      echo "ssh_user=${ssh_user}"
      echo "private_key=${ACCESS_DIR}/id_ed25519"
      echo "known_hosts=${ACCESS_DIR}/known_hosts"
    } >> "${GITHUB_OUTPUT}"
  fi
  trap - EXIT
  echo "Temporary SSH access to ${GCP_INSTANCE} is open from ${source_ip}/32 via ${ACCESS_RULE_NAME}; the OS Login key expires after ${ttl}."
}

case "${1:-}" in
  open) common_inputs; open_access ;;
  close)
    common_inputs
    close_access || { echo '::error::Temporary SSH access was not fully revoked.' >&2; exit 1; }
    echo "Temporary SSH access ${ACCESS_RULE_NAME} is closed."
    ;;
  *) echo 'usage: gcp-temporary-ssh-access.sh open|close' >&2; exit 2 ;;
esac
