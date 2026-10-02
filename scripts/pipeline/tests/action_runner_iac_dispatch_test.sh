#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
script="${repo_root}/scripts/pipeline/action-runner-iac.sh"
workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT

mkdir -p "${workdir}/bin" "${workdir}/vps"
cat >"${workdir}/bin/python3" <<'EOF'
#!/usr/bin/env bash
printf 'python3 %s\n' "$*" >>"${COMMAND_LOG}"
EOF
cat >"${workdir}/bin/terraform" <<'EOF'
#!/usr/bin/env bash
printf 'terraform %s\n' "$*" >>"${COMMAND_LOG}"
EOF
chmod +x "${workdir}/bin/python3" "${workdir}/bin/terraform"

printf '%s\n' '{"web-saas":{"ip":"192.0.2.10"}}' >"${workdir}/vps/cmdb.json"
command_env=(PATH="${workdir}/bin:${PATH}" COMMAND_LOG="${workdir}/commands.log")

(cd "${workdir}/vps" && env "${command_env[@]}" VAULT_ENV_PATH=uat bash "${script}" render)
(cd "${workdir}/vps" && env "${command_env[@]}" VAULT_ENV_PATH=uat TF_STATE_ENDPOINT=https://s3.example.test TF_STATE_BUCKET=bucket TF_STATE_ACCESS_KEY=access TF_STATE_SECRET_KEY=secret TF_STATE_REGION=ap-northeast-1 bash "${script}" terraform-init)
(cd "${workdir}/vps" && env "${command_env[@]}" TERRAFORM_ACTION=plan bash "${script}" terraform-action)
(cd "${workdir}/vps" && env "${command_env[@]}" VAULT_ENV_PATH=uat bash "${script}" inventory)

matrix_output="${workdir}/matrix.out"
(cd "${workdir}/vps" && env "${command_env[@]}" GITHUB_OUTPUT="${matrix_output}" bash "${script}" build-matrix)
grep -Fxq 'hosts=["web-saas"]' "${matrix_output}"
grep -Fxq 'count=1' "${matrix_output}"

grep -Fq 'python3 scripts/generate.py render' "${workdir}/commands.log"
grep -Fq 'python3 scripts/generate.py inventory' "${workdir}/commands.log"
grep -Fq 'terraform init -input=false' "${workdir}/commands.log"
grep -Fq 'terraform/uat/platform-ops-toolkit/vultr-vps/primary/action-runner/terraform.tfstate' "${workdir}/commands.log"
grep -Fq 'use_lockfile=true' "${workdir}/commands.log"
grep -Fq 'terraform plan -auto-approve -input=false' "${workdir}/commands.log"

if bash "${script}" unknown >/dev/null 2>&1; then
  echo 'unknown action-runner IAC operation unexpectedly succeeded' >&2
  exit 1
fi

echo "action_runner_iac_dispatch_test: PASS"
