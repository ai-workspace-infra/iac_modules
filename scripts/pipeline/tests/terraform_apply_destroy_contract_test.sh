#!/usr/bin/env bash
set -euo pipefail

pipeline_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
apply_script="${pipeline_dir}/terraform-apply-destroy.sh"

# A normal UAT apply must refuse a plan that deletes or replaces resources.
grep -Fq 'ENV_STEPS_ROUTE_OUTPUTS_STATE_KEY:-}' "${apply_script}"
grep -Fq 'index("delete")' "${apply_script}"

# destroy is guarded by the destroy-scope assertion that lives next to this
# script; a dangling path would turn the guard into exit 127 on every destroy.
grep -Fq '/assert-destroy-scope.sh"' "${apply_script}"
test -x "${pipeline_dir}/assert-destroy-scope.sh" || {
  echo "assert-destroy-scope.sh must be executable next to terraform-apply-destroy.sh" >&2
  exit 1
}

# The guard has to run before terraform destroy, not after it.
workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT
mkdir -p "${workdir}/bin" "${workdir}/pipeline"
cp "${apply_script}" "${workdir}/pipeline/terraform-apply-destroy.sh"
cat >"${workdir}/pipeline/assert-destroy-scope.sh" <<'GUARD'
#!/usr/bin/env bash
echo "guard" >>"${CALL_LOG}"
exit "${GUARD_EXIT:-0}"
GUARD
cat >"${workdir}/bin/terraform" <<'TERRAFORM'
#!/usr/bin/env bash
echo "terraform $*" >>"${CALL_LOG}"
TERRAFORM
chmod +x "${workdir}/bin/terraform" "${workdir}/pipeline/assert-destroy-scope.sh" "${workdir}/pipeline/terraform-apply-destroy.sh"

run_destroy() {
  (cd "${workdir}" && PATH="${workdir}/bin:${PATH}" CALL_LOG="${workdir}/calls.log" \
    ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_ACTION=destroy \
    ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE=uat-test \
    ENV_STEPS_ROUTE_OUTPUTS_CLOUD_PROVIDER=vultr-vps \
    "$@" "${workdir}/pipeline/terraform-apply-destroy.sh")
}

: >"${workdir}/calls.log"
run_destroy env
[[ "$(sed -n 2p "${workdir}/calls.log")" == guard ]] || { echo "destroy scope guard did not run before terraform destroy" >&2; cat "${workdir}/calls.log" >&2; exit 1; }
[[ "$(sed -n 3p "${workdir}/calls.log")" == "terraform destroy -auto-approve -input=false" ]] || { cat "${workdir}/calls.log" >&2; exit 1; }

: >"${workdir}/calls.log"
if run_destroy env GUARD_EXIT=1; then
  echo "terraform destroy must not run when the destroy scope guard fails" >&2
  exit 1
fi
if grep -Fq 'terraform destroy' "${workdir}/calls.log"; then
  echo "terraform destroy ran after a failed destroy scope guard" >&2
  exit 1
fi

echo "terraform_apply_destroy_contract_test: PASS"
