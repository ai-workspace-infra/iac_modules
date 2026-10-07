#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
temporary="$(mktemp -d)"
trap 'rm -rf "$temporary"' EXIT
mkdir -p "$temporary/bin" "$temporary/lab"
cat > "$temporary/bin/aws" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$MOCK_AWS_CALLS"
SH
chmod 755 "$temporary/bin/aws"
printf 'xcl-123-4' > "$temporary/lab/run-id"
printf '{"expires_at":"2030-01-01T00:00:00Z"}' > "$temporary/lab/variables.json"

export PATH="$temporary/bin:$PATH" LAB_DIR="$temporary/lab" MOCK_AWS_CALLS="$temporary/aws-calls"
export TF_STATE_ACCESS_KEY=test TF_STATE_SECRET_ACCESS_KEY=test TF_STATE_SECRET_KEY=test
export TF_STATE_REGION=auto TF_STATE_ENDPOINT=https://state.invalid TF_STATE_BUCKET=state-bucket
IAC_REF="$(printf 'a%.0s' {1..40})"
GITOPS_REF="$(printf 'b%.0s' {1..40})"
PLAYBOOKS_REF="$(printf 'c%.0s' {1..40})"
export IAC_REF GITOPS_REF PLAYBOOKS_REF
export CLI_RELEASE_TAG=v0.1.14 GATEWAY_RELEASE_TAG=v0.1.8 XRAY_RELEASE_TAG=v26.3.27
export GATEWAY_PROVIDER=external EXTERNAL_GATEWAY_ID=gw-uat EXTERNAL_NETWORK_ID=net-uat
export EXTERNAL_GATEWAY_SERVER_NAME=tw-xconnect.svc.plus GATEWAY_WIREGUARD_ADDRESS=10.77.0.1/32

bash "$root/scripts/pipeline/xconnect-lab-lease.sh" create
jq -e --arg iac "$IAC_REF" --arg gitops "$GITOPS_REF" --arg playbooks "$PLAYBOOKS_REF" '
  .run == "xcl-123-4" and .expires_at == "2030-01-01T00:00:00Z" and
  .inputs.mode == "cleanup" and .inputs.cleanup_run == .run and
  .inputs.iac_ref == $iac and .inputs.gitops_ref == $gitops and .inputs.playbooks_ref == $playbooks
' "$LAB_DIR/lease.json" >/dev/null
[[ "$(python3 -c 'import os, stat, sys; print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode))[2:])' "$LAB_DIR/lease.json")" == 600 ]]
grep -Fq 's3api put-object --bucket state-bucket --key runs/uat/svc.plus/aws-cloud/primary/xconnect-lab/xcl-123-4.json' "$MOCK_AWS_CALLS"

bash "$root/scripts/pipeline/xconnect-lab-lease.sh" delete
grep -Fq 's3api delete-object --bucket state-bucket --key runs/uat/svc.plus/aws-cloud/primary/xconnect-lab/xcl-123-4.json' "$MOCK_AWS_CALLS"

export IAC_REF=main
if bash "$root/scripts/pipeline/xconnect-lab-lease.sh" create >"$temporary/out" 2>"$temporary/err"; then
  echo 'lease accepted a mutable IaC ref' >&2
  exit 1
fi
grep -Fq 'IAC_REF must be an immutable commit SHA' "$temporary/err"
echo 'xconnect-lab-lease-test: PASS'
