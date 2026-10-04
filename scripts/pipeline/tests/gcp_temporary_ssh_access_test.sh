#!/usr/bin/env bash
# Behaviour of gcp-temporary-ssh-access.sh against a stateful fake gcloud:
# open/close round trip, rollback of a failed open, refusal to adopt or reuse,
# fail-closed revocation, and input validation before any write.
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
script="${root_dir}/scripts/pipeline/gcp-temporary-ssh-access.sh"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

mkdir -p "${work}/bin"
cat > "${work}/bin/gcloud" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${FAKE_STATE}/gcloud.log"
arg_value() { local key="$1"; shift; for a in "$@"; do [[ "${a}" == "${key}="* ]] && printf '%s' "${a#*=}"; done; }
case "$*" in
  "compute instances describe "*"--format=value(status)")
    cat "${FAKE_STATE}/status" ;;
  "compute instances describe "*"--format=json")
    jq -n --arg status "$(cat "${FAKE_STATE}/status")" --arg ip "${FAKE_NAT_IP-34.80.12.34}" --arg tags "${FAKE_TAGS-iam,https}" \
      '{status:$status, networkInterfaces:[{accessConfigs:[(if $ip == "" then {} else {natIP:$ip} end)]}],
        tags:{items:($tags | split(",") | map(select(. != "")))}}' ;;
  "compute instances describe "*"--format=value(lastStopTimestamp,lastSuspendedTimestamp)")
    echo '2026-10-04T00:00:00Z' ;;
  "compute operations list "*) echo '2026-10-04T00:00:00Z stop DONE' ;;
  "compute instances start "*) echo RUNNING > "${FAKE_STATE}/status" ;;
  "compute firewall-rules list "*)
    [[ -z "${FAKE_LIST_FAIL:-}" ]] || exit 1
    rule="$(arg_value --filter "$@")"; rule="${rule#name=(}"; rule="${rule%)}"
    [[ -f "${FAKE_STATE}/rules/${rule}" ]] && printf '%s\n' "${rule}"
    exit 0 ;;
  "compute firewall-rules create "*)
    [[ -z "${FAKE_CREATE_FAIL:-}" ]] || exit 1
    printf '%s\n' "$*" > "${FAKE_STATE}/rules/$4" ;;
  "compute firewall-rules delete "*)
    [[ -z "${FAKE_DELETE_FAIL:-}" ]] || exit 1
    rm -f "${FAKE_STATE}/rules/$4" ;;
  "compute os-login ssh-keys add "*)
    [[ -z "${FAKE_ADD_FAIL:-}" ]] || exit 1
    cp "$(arg_value --key-file "$@")" "${FAKE_STATE}/keys/registered.pub" ;;
  "compute os-login ssh-keys remove "*)
    [[ -z "${FAKE_REMOVE_FAIL:-}" ]] || exit 1
    rm -f "${FAKE_STATE}/keys/registered.pub" ;;
  "compute os-login describe-profile "*)
    printf '{"posixAccounts":[{"operatingSystemType":"LINUX","username":"%s"}]}\n' "${FAKE_USER:-sa_112233445566778899001}" ;;
  *) echo "unexpected gcloud $*" >&2; exit 9 ;;
esac
FAKE
cat > "${work}/bin/curl" <<'FAKE'
#!/usr/bin/env bash
printf '%s' "${FAKE_RUNNER_IP:-20.30.40.50}"
FAKE
# The runner image has OpenSSH; the stub keeps this test independent of it.
cat > "${work}/bin/ssh-keygen" <<'FAKE'
#!/usr/bin/env bash
while (($#)); do [[ "$1" == -f ]] && path="$2"; shift; done
printf 'PRIVATE-KEY-MATERIAL\n' > "${path}"; chmod 600 "${path}"
printf 'ssh-ed25519 AAAAFAKE ci\n' > "${path}.pub"
FAKE
chmod +x "${work}/bin/"*

reset_state() {
  rm -rf "${work}/state" "${work}/access"
  mkdir -p "${work}/state/rules" "${work}/state/keys"
  echo "${1:-RUNNING}" > "${work}/state/status"
  : > "${work}/output"
}
run() { # <subcommand> [env...]
  local sub="$1"; shift
  env PATH="${work}/bin:${PATH}" FAKE_STATE="${work}/state" GITHUB_OUTPUT="${work}/output" \
    GCP_PROJECT_ID=open-platform-shared-510113 GCP_ZONE=asia-east1-a GCP_INSTANCE=iam-shared-0 \
    GCP_NETWORK=iam ACCESS_RULE_NAME=zitadel-ssh-4242-1 ACCESS_DIR="${work}/access" \
    "$@" bash "${script}" "${sub}" > "${work}/out" 2>&1
}
writes() { # number of mutating gcloud calls so far
  [[ -f "${work}/state/gcloud.log" ]] || { echo 0; return; }
  grep -cE 'firewall-rules (create|delete)|ssh-keys (add|remove)|instances start' "${work}/state/gcloud.log" || true
}

# --- open/close round trip ----------------------------------------------------
reset_state
run open || { cat "${work}/out" >&2; fail "open must succeed for a running VM"; }
rule_args="$(cat "${work}/state/rules/zitadel-ssh-4242-1")"
for expected in --network=iam --direction=INGRESS --action=ALLOW --rules=tcp:22 \
                --source-ranges=20.30.40.50/32 --target-tags=iam,https; do
  [[ " ${rule_args} " == *" ${expected} "* ]] || fail "firewall rule must carry ${expected}: ${rule_args}"
done
grep -q -- 'ssh-keys add --project=open-platform-shared-510113 --key-file=[^ ]*/id_ed25519.pub --ttl=20m$' "${work}/state/gcloud.log" \
  || fail "the key must be registered with the default 20m TTL"
[[ -f "${work}/state/keys/registered.pub" ]] || fail "the one-run key must be registered"
jq -e --arg dir "${work}/access" '.instance == "iam-shared-0" and .target_ip == "34.80.12.34"
  and .target_tags == ["iam","https"] and .ssh_user == "sa_112233445566778899001"
  and .private_key == ($dir + "/id_ed25519") and .known_hosts == ($dir + "/known_hosts")
  and .firewall_rule == "zitadel-ssh-4242-1" and .source_range == "20.30.40.50/32" and .oslogin_key_ttl == "20m"' \
  "${work}/access/access.json" >/dev/null || fail "access.json must carry the target facts"
[[ "$(stat -c %a "${work}/access")" == 700 && "$(stat -c %a "${work}/access/access.json")" == 600 ]] || fail "access files must be private"
grep -qx "target_ip=34.80.12.34" "${work}/output" && grep -qx "private_key=${work}/access/id_ed25519" "${work}/output" \
  || fail "GITHUB_OUTPUT must carry the facts"
! grep -q 'PRIVATE-KEY-MATERIAL\|sa_112233445566778899001' "${work}/out" || fail "neither the private key nor the OS Login user may be printed"
grep -q 'instances describe iam-shared-0 --project open-platform-shared-510113 --zone asia-east1-a --format=value(status)' \
  "${work}/state/gcloud.log" || fail "open must reconcile the VM runtime first"

run close || { cat "${work}/out" >&2; fail "close must succeed"; }
[[ ! -e "${work}/state/rules/zitadel-ssh-4242-1" ]] || fail "close must delete the rule"
[[ ! -e "${work}/state/keys/registered.pub" ]] || fail "close must revoke the key"
[[ ! -e "${work}/access" ]] || fail "close must remove ACCESS_DIR"
run close || fail "close must be idempotent"
echo "PASS: open records target facts and a /32 tag-scoped rule; close revokes everything, twice"

# A stopped VM is started first; GITHUB_ACTIONS masks the OS Login user.
reset_state TERMINATED
run open GITHUB_ACTIONS=true || { cat "${work}/out" >&2; fail "a stopped VM must be started and opened"; }
grep -q '^compute instances start iam-shared-0' "${work}/state/gcloud.log" || fail "a stopped VM must be started"
grep -qx '::add-mask::sa_112233445566778899001' "${work}/out" || fail "the OS Login user must be masked in Actions"
run close
# Explicit tags and source address override discovery.
reset_state
run open TARGET_TAGS=vault SOURCE_IP=52.1.2.3 OSLOGIN_KEY_TTL=35m || fail "explicit tags and source must be accepted"
grep -q -- '--source-ranges=52.1.2.3/32 --target-tags=vault ' "${work}/state/rules/zitadel-ssh-4242-1" || fail "overrides must scope the rule"
grep -q -- '--ttl=35m$' "${work}/state/gcloud.log" || fail "the TTL override must be used"
run close
echo "PASS: stopped VM started, user masked, explicit tags/source/TTL honoured"

# --- a failed open rolls back -----------------------------------------------------
reset_state
run open FAKE_CREATE_FAIL=1 && fail "a failed firewall create must fail open"
grep -q 'rolling back' "${work}/out" || fail "a failed open must say it rolls back"
[[ ! -e "${work}/state/keys/registered.pub" ]] || fail "rollback must revoke the registered key"
[[ ! -e "${work}/access" ]] || fail "rollback must remove ACCESS_DIR"
for case in "FAKE_NAT_IP=" "FAKE_TAGS=" "SOURCE_IP=10.0.0.8" "SOURCE_IP=not-an-ip" "FAKE_USER=Root!"; do
  reset_state
  run open "${case}" && fail "open must refuse: ${case}"
  [[ ! -e "${work}/state/keys/registered.pub" && -z "$(ls "${work}/state/rules")" && ! -e "${work}/access" ]] \
    || fail "nothing may remain after a refused open: ${case}"
done
reset_state TERMINATED
run open ENSURE_RUNNING=false && fail "a VM that is not RUNNING must be refused"
[[ "$(writes)" == 0 ]] || fail "a VM that is not RUNNING must not get access"
echo "PASS: failed or refused opens leave no key, rule or directory"

# --- refuse to adopt or reuse, and validate before any write --------------------
reset_state
echo foreign > "${work}/state/rules/zitadel-ssh-4242-1"
run open && fail "an existing rule must not be adopted"
[[ "$(cat "${work}/state/rules/zitadel-ssh-4242-1")" == foreign ]] || fail "a foreign rule must be left untouched"
[[ "$(writes)" == 0 ]] || fail "refusing to adopt must not write"
reset_state
run open FAKE_LIST_FAIL=1 && fail "an unreadable rule list must refuse open"
[[ "$(writes)" == 0 ]] || fail "an unreadable rule list must not write"
for case in ACCESS_RULE_NAME=Bad_Rule ACCESS_RULE_NAME= ACCESS_DIR=relative/dir ACCESS_DIR=/ GCP_ZONE=asia \
            GCP_PROJECT_ID=X OSLOGIN_KEY_TTL=0m OSLOGIN_KEY_TTL=3h OSLOGIN_KEY_TTL=121m GCP_INSTANCE=; do
  reset_state
  run open "${case}" && fail "invalid input must be refused: ${case}"
  [[ "$(writes)" == 0 ]] || fail "invalid input must be refused before any write: ${case}"
done
reset_state
mkdir -p "${work}/access"
run open && fail "an existing ACCESS_DIR must not be reused"
[[ -d "${work}/access" && "$(writes)" == 0 ]] || fail "a reused ACCESS_DIR must be left alone"
run bogus && fail "an unknown subcommand must fail"
echo "PASS: no adoption, no reuse, invalid input refused before writes"

# --- close fails closed but keeps revoking ------------------------------------------
reset_state
run open
run close FAKE_DELETE_FAIL=1 && fail "a rule that cannot be deleted must fail close"
grep -q 'still present' "${work}/out" || fail "close must report the remaining rule"
[[ ! -e "${work}/state/keys/registered.pub" && ! -e "${work}/access" ]] || fail "close must still revoke the key and remove the directory"
run close FAKE_LIST_FAIL=1 && fail "an unreadable rule list must fail close"
run close || fail "a later close must finish the revocation"
reset_state
run open
run close FAKE_REMOVE_FAIL=1 && fail "a key that cannot be revoked must fail close"
[[ ! -e "${work}/state/rules/zitadel-ssh-4242-1" ]] || fail "the rule must still be deleted"
echo "PASS: close reports every failed revocation and still revokes the rest"

echo "gcp_temporary_ssh_access_test: PASS"
