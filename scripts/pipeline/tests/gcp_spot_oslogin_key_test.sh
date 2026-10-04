#!/usr/bin/env bash
# Behaviour of the OS Login deploy-key registration for GCP Spot VMs.
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
script="${root_dir}/scripts/pipeline/register-gcp-oslogin-key.sh"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

mkdir -p "${work}/bin"
cat > "${work}/bin/gcloud" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${FAKE_GCLOUD_LOG}"
for arg in "$@"; do
  case "${arg}" in
    --key-file=*) cp "${arg#--key-file=}" "${FAKE_GCLOUD_LOG}.key" ;;
  esac
done
if [[ "$*" == "config get-value account" ]]; then
  [[ -f "${FAKE_GCLOUD_LOG}.account" ]] && cat "${FAKE_GCLOUD_LOG}.account"
  printf '%s\n' "${FAKE_ACTIVE_ACCOUNT:-}"
  exit 0
fi
if [[ "$*" == "--quiet auth login --cred-file="* ]]; then
  echo "Authenticated with external account credentials for: [deploy@example.iam.gserviceaccount.com]" >&2
  echo deploy@example.iam.gserviceaccount.com > "${FAKE_GCLOUD_LOG}.account"
  exit 0
fi
if [[ "$*" == *"describe-profile"* ]]; then
  printf '{"posixAccounts":[{"operatingSystemType":"LINUX","username":"%s"}]}\n' "${FAKE_OSLOGIN_USER}"
fi
FAKE
chmod +x "${work}/bin/gcloud"

run_case() {
  local name="$1" manifest="$2"
  shift 2
  : > "${work}/${name}.env"
  : > "${work}/${name}.gcloud"
  rm -rf "${work}/tmp" && mkdir "${work}/tmp"
  env PATH="${work}/bin:${PATH}" TMPDIR="${work}/tmp" \
    RESOURCES_MANIFEST="${work}/${name}.json" GCP_PROJECT_ID=open-platform-uat \
    GITHUB_ENV="${work}/${name}.env" FAKE_GCLOUD_LOG="${work}/${name}.gcloud" \
    GOOGLE_GHA_CREDS_PATH="${work}/gha-creds.json" \
    SSH_PUBLIC_DEPLOY_KEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey deploy' \
    FAKE_OSLOGIN_USER=sa_123456789012345678901 "$@" \
    bash -c 'printf "%s" "$1" > "${RESOURCES_MANIFEST}"; exec "$2"' _ "${manifest}" "${script}" \
    > "${work}/${name}.out" 2>&1
}

oslogin='{"spot_vms":[{"name":"ai-workspace-uat","enable_oslogin":true},{"name":"legacy","public_ip":true}]}'

# A namespace without OS Login VMs keeps the metadata key and calls nothing.
run_case none '{"spot_vms":[{"name":"legacy"}],"vault_nodes":[{"name":"v","enable_oslogin":true}]}' \
  || fail "a namespace without OS Login Spot VMs must succeed"
[[ ! -s "${work}/none.gcloud" ]] || fail "no gcloud call is expected without OS Login Spot VMs"
[[ ! -s "${work}/none.env" ]] || fail "no username is exported without OS Login Spot VMs"

# OS Login VMs: register with an expiry, refresh it, export the user.
run_case on "${oslogin}" || { cat "${work}/on.out" >&2; fail "OS Login registration must succeed"; }
grep -q '^compute os-login ssh-keys add --project=open-platform-uat --key-file=[^ ]* --ttl=6h$' "${work}/on.gcloud" \
  || fail "the key must be added with the default 6h TTL"
grep -q '^compute os-login ssh-keys update --project=open-platform-uat --key-file=[^ ]* --ttl=6h$' "${work}/on.gcloud" \
  || fail "the expiry of an already registered key must be refreshed"
[[ "$(grep -n 'ssh-keys' "${work}/on.gcloud" | cut -d: -f2- | sed -n 2p)" == *"ssh-keys update"* ]] || fail "update must follow add"
# Without an active account (WIF credential-file override), activate the credential first.
grep -Fxq -- "--quiet auth login --cred-file=${work}/gha-creds.json" "${work}/on.gcloud" \
  || fail "the WIF credential must be activated when no gcloud account is active"
[[ "$(grep -n 'auth login' "${work}/on.gcloud" | cut -d: -f1)" -lt "$(grep -n 'ssh-keys add' "${work}/on.gcloud" | cut -d: -f1)" ]] \
  || fail "the credential must be activated before the key is added"
! grep -q 'deploy@example' "${work}/on.out" || fail "the deploy principal must not be printed"

# An already active account is used as is.
run_case active "${oslogin}" FAKE_ACTIVE_ACCOUNT=deploy@example.iam.gserviceaccount.com \
  || fail "registration with an active account must succeed"
! grep -q 'auth login' "${work}/active.gcloud" || fail "an active gcloud account must not be replaced"
grep -Fxq 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey deploy' "${work}/on.gcloud.key" \
  || fail "the Vault deploy public key must be registered"
grep -Fxq 'GCP_OSLOGIN_USERNAME=sa_123456789012345678901' "${work}/on.env" || fail "the OS Login user must reach GITHUB_ENV"
grep -Fxq '::add-mask::sa_123456789012345678901' "${work}/on.out" || fail "the OS Login user must be masked"
[[ "$(grep -c 'sa_123456789012345678901' "${work}/on.out")" == 1 ]] || fail "the OS Login user must be printed only as a mask"
! grep -q 'AAAAC3NzaC1lZDI1NTE5AAAAITestKey' "${work}/on.out" || fail "the key must not be printed"
[[ -z "$(ls -A "${work}/tmp")" ]] || fail "the temporary key file must be removed"

# Refusals.
run_case ttl "${oslogin}" OSLOGIN_KEY_TTL=forever && fail "an invalid TTL must be refused"
[[ ! -s "${work}/ttl.gcloud" ]] || fail "an invalid TTL must be refused before calling gcloud"
run_case user "${oslogin}" FAKE_OSLOGIN_USER='root;id' && fail "an invalid OS Login user must be refused"
[[ ! -s "${work}/user.env" ]] || fail "an invalid OS Login user must not be exported"
run_case nokey "${oslogin}" SSH_PUBLIC_DEPLOY_KEY= && fail "a missing deploy key must be refused"

# Starting a stopped VM reports started=true so the workflow refreshes outputs.
mkdir -p "${work}/rt"
cat > "${work}/rt/gcloud" <<'FAKE'
#!/usr/bin/env bash
state="${FAKE_RT_STATE}"
if [[ "$*" == *"instances describe"* ]]; then
  if [[ -f "${state}" ]]; then echo RUNNING; else echo "${FAKE_RT_INITIAL}"; fi
elif [[ "$*" == *"instances start"* || "$*" == *"instances resume"* ]]; then
  printf '%s\n' "$*" >> "${FAKE_RT_OPERATIONS}"
  touch "${state}"
fi
FAKE
chmod +x "${work}/rt/gcloud"
printf '%s' '{"spot_vms":[{"name":"web-saas-uat","zone":"asia-east1-a"}]}' > "${work}/rt/manifest.json"
runtime="${root_dir}/scripts/pipeline/ensure-gcp-vm-running.py"
for initial in TERMINATED RUNNING; do
  rm -f "${work}/rt/state" "${work}/rt/out"
  PATH="${work}/rt:${PATH}" FAKE_RT_STATE="${work}/rt/state" FAKE_RT_INITIAL="${initial}" \
    FAKE_RT_OPERATIONS="${work}/rt/operations" GITHUB_OUTPUT="${work}/rt/out" \
    python3 "${runtime}" --manifest "${work}/rt/manifest.json" --project p --interval 1 --timeout 5 >/dev/null
  expected=false; [[ "${initial}" == TERMINATED ]] && expected=true
  grep -Fxq "started=${expected}" "${work}/rt/out" || fail "a ${initial} VM must report started=${expected}"
done

# Shared service nodes resolve one reviewed GitOps identity in the Toolkit
# caller. The same owner executor must support that exact target and resume a
# suspended VM instead of attempting an invalid start operation.
for initial in TERMINATED SUSPENDED RUNNING; do
  rm -f "${work}/rt/state" "${work}/rt/out" "${work}/rt/operations"
  PATH="${work}/rt:${PATH}" FAKE_RT_STATE="${work}/rt/state" FAKE_RT_INITIAL="${initial}" \
    FAKE_RT_OPERATIONS="${work}/rt/operations" GITHUB_OUTPUT="${work}/rt/out" \
    python3 "${runtime}" --instance observability-shared-0 --zone asia-east1-a \
      --project p --interval 1 --timeout 5 >/dev/null
  expected=false; [[ "${initial}" != RUNNING ]] && expected=true
  grep -Fxq "started=${expected}" "${work}/rt/out" || fail "single ${initial} VM must report started=${expected}"
  if [[ "${initial}" == SUSPENDED ]]; then
    grep -Fq 'instances resume observability-shared-0' "${work}/rt/operations" || fail 'suspended VM must resume'
  fi
done
if python3 "${runtime}" --instance 'bad;id' --zone asia-east1-a --project p >/dev/null 2>&1; then
  fail 'invalid instance identity was accepted'
fi

echo "GCP Spot OS Login deploy-key tests passed."
