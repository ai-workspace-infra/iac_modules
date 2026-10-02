#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="${script_dir}/../verify-aws-boot-health.sh"
workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT

mkdir -p "${workdir}/bin"
cat >"${workdir}/cmdb.json" <<'JSON'
{
  "hk-xconnect.onwalk.net": {
    "name": "agent-proxy-hk",
    "instance_id": "i-hk",
    "cloud_region": "ap-east-1",
    "ip": "198.51.100.10"
  }
}
JSON

cat >"${workdir}/bin/aws" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${TEST_WORKDIR}/aws-commands.log"
case "$*" in
  *describe-instance-status*) printf '%s\n' "${TEST_INSTANCE_STATUS}" ;;
  *get-console-output*) printf '%s\n' 'cloud-init: ssh.service failed to start' ;;
  *) echo "unexpected aws invocation: $*" >&2; exit 1 ;;
esac
SCRIPT
chmod +x "${workdir}/bin/aws" "${script}"

cat >"${workdir}/bin/ssh-keyscan" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${TEST_WORKDIR}/ssh-keyscan-commands.log"
if [[ "${TEST_SSH_READY:-true}" == 'true' ]]; then
  printf '%s\n' '198.51.100.10 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey'
fi
SCRIPT
chmod +x "${workdir}/bin/ssh-keyscan"

TEST_WORKDIR="${workdir}" \
TEST_INSTANCE_STATUS='running ok ok' \
TEST_SSH_READY=true \
PATH="${workdir}/bin:${PATH}" \
CMDB_FILE="${workdir}/cmdb.json" \
AWS_BOOT_HEALTH_TIMEOUT_SECONDS=0 \
bash "${script}" >"${workdir}/healthy.log"

grep -Fq 'passed EC2 status and SSH banner checks' "${workdir}/healthy.log"
grep -Fq -- '--region ap-east-1 --instance-ids i-hk --include-all-instances' "${workdir}/aws-commands.log"
grep -Fq -- '-T 5 -p 22 198.51.100.10' "${workdir}/ssh-keyscan-commands.log"
if grep -Fq 'get-console-output' "${workdir}/aws-commands.log"; then
  echo "healthy instances must not request console output" >&2
  exit 1
fi

: >"${workdir}/aws-commands.log"
if TEST_WORKDIR="${workdir}" \
  TEST_INSTANCE_STATUS='running ok initializing' \
  PATH="${workdir}/bin:${PATH}" \
  CMDB_FILE="${workdir}/cmdb.json" \
  AWS_BOOT_HEALTH_TIMEOUT_SECONDS=0 \
  bash "${script}" >"${workdir}/failed.log" 2>&1; then
  echo "an instance with an initializing status must fail at the deadline" >&2
  exit 1
fi

grep -Fq 'did not pass both EC2 status checks' "${workdir}/failed.log"
grep -Fq 'cloud-init: ssh.service failed to start' "${workdir}/failed.log"
grep -Fq -- '--region ap-east-1 --instance-id i-hk --latest' "${workdir}/aws-commands.log"

: >"${workdir}/aws-commands.log"
if TEST_WORKDIR="${workdir}" \
  TEST_INSTANCE_STATUS='running ok ok' \
  TEST_SSH_READY=false \
  PATH="${workdir}/bin:${PATH}" \
  CMDB_FILE="${workdir}/cmdb.json" \
  AWS_BOOT_HEALTH_TIMEOUT_SECONDS=0 \
  AWS_SSH_BANNER_TIMEOUT_SECONDS=0 \
  bash "${script}" >"${workdir}/ssh-failed.log" 2>&1; then
  echo "an instance without an SSH banner must fail at the deadline" >&2
  exit 1
fi

grep -Fq 'did not return an SSH banner' "${workdir}/ssh-failed.log"
grep -Fq 'cloud-init: ssh.service failed to start' "${workdir}/ssh-failed.log"
grep -Fq 'get-console-output' "${workdir}/aws-commands.log"

echo "aws_boot_health_test: PASS"
