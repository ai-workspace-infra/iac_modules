#!/usr/bin/env bash
set -euo pipefail
umask 077
die() { echo "::error::$*" >&2; exit 1; }
for name in XCONNECT_IAC_OPERATION IAC_ROOT GITOPS_ROOT XCONNECT_DECLARATION LAB_DIR TF_VAR_run_id MODE RUNNER_TEMP; do
  [[ -n "${!name:-}" ]] || die "$name is required"
done
[[ "$XCONNECT_IAC_OPERATION" =~ ^(preflight|prepare|apply|cleanup)$ ]] || die 'Unsupported XConnect IaC operation'
[[ "$MODE" =~ ^(dry-run|apply|cleanup)$ ]] || die 'Invalid Toolkit mode'
TF_VAR_run_id="${TF_VAR_run_id:?TF_VAR_run_id is required}"
[[ "$TF_VAR_run_id" =~ ^xcl-[0-9]+-[0-9]+$ ]] || die 'Invalid exact run identity'
[[ "$LAB_DIR" == "$RUNNER_TEMP/"* && "$LAB_DIR" != *'/../'* ]] || die 'LAB_DIR must remain below RUNNER_TEMP'
TF="$IAC_ROOT/vpn-overlay/xconnect-lab"
[[ -d "$TF" && -f "$XCONNECT_DECLARATION" ]] || die 'Fixed owner module or declaration is missing'
mkdir -p "$LAB_DIR"
printf '%s' "$TF_VAR_run_id" > "$LAB_DIR/run-id"

diagnose() {
  local command="$1" log="$2" code="$3"
  python3 "$IAC_ROOT/scripts/pipeline/xconnect-terraform-diagnostics.py" "$command" "$log" "$code" || true
}
tf() {
  local command="$1"; shift
  local log="$LAB_DIR/terraform-${command}.log" code
  if terraform -chdir="$TF" "$command" -no-color -json "$@" >"$log" 2>&1; then return 0; else code=$?; fi
  diagnose "$command" "$log" "$code"; exit "$code"
}
tf_read() {
  local command="$1" destination="$2"; shift 2
  local log="$LAB_DIR/terraform-${command}.log" code
  if terraform -chdir="$TF" "$command" "$@" >"$destination" 2>"$log"; then return 0; else code=$?; fi
  diagnose "$command" "$log" "$code"
  die 'Lab state/output inspection failed; cleanup is unverified and requires exact-run recovery'
}

case "$XCONNECT_IAC_OPERATION" in
  preflight)
    test -f "$TF/expiry_timer_test.sh" || die 'Owner revision lacks absolute-expiry protection'
    bash "$TF/contract_test.sh"
    terraform -chdir="$TF" fmt -check
    terraform -chdir="$TF" init -backend=false -input=false >"$LAB_DIR/terraform-init.log" 2>&1 || { code=$?; diagnose init "$LAB_DIR/terraform-init.log" "$code"; exit "$code"; }
    tf validate
    echo 'IaC owner preflight passed without resource or state changes.'
    ;;
  prepare)
    [[ "$(aws sts get-caller-identity --query Account --output text)" == "$(jq -r .spec.aws.account_id "$XCONNECT_DECLARATION")" ]] || die 'AWS account mismatch'
    python3 "$IAC_ROOT/scripts/pipeline/xconnect-lab-contract.py" backend "$LAB_DIR" "$XCONNECT_DECLARATION"
    terraform -chdir="$TF" init -reconfigure -input=false -backend-config="$LAB_DIR/backend.json" >"$LAB_DIR/terraform-init.log" 2>&1 || { code=$?; diagnose init "$LAB_DIR/terraform-init.log" "$code"; exit "$code"; }
    touch "$LAB_DIR/backend-ready"
    if [[ "$MODE" == apply ]]; then
      for name in LAB_VLESS_ID ZERO_SERVICE_TOKEN ZERO_OWNER_EMAIL; do [[ -n "${!name:-}" ]] || die "Missing runtime field $name"; done
      ssh-keygen -q -t ed25519 -N '' -f "$LAB_DIR/id_ed25519"
      python3 "$IAC_ROOT/scripts/pipeline/xconnect-lab-contract.py" resources "$LAB_DIR" "$XCONNECT_DECLARATION"
      cp "$LAB_DIR/variables.json" "$TF/terraform.auto.tfvars.json"
      tf plan -input=false -out="$LAB_DIR/plan"
    fi
    ;;
  apply)
    [[ "$MODE" == apply && -f "$LAB_DIR/backend-ready" && -f "$LAB_DIR/plan" ]] || die 'Prepared same-run plan is required'
    bash "$IAC_ROOT/scripts/pipeline/xconnect-lab-lease.sh" create
    touch "$LAB_DIR/apply-started"
    tf apply -input=false "$LAB_DIR/plan"
    tf_read output "$LAB_DIR/outputs.json" -json
    ;;
  cleanup)
    [[ "$MODE" == cleanup && -f "$LAB_DIR/backend-ready" ]] || die 'Explicit cleanup state is not initialized'
    tf_read show "$LAB_DIR/state.json" -json
    python3 "$IAC_ROOT/scripts/pipeline/xconnect-lab-contract.py" cleanup "$LAB_DIR" "$XCONNECT_DECLARATION"
    cp "$LAB_DIR/variables.json" "$TF/terraform.auto.tfvars.json"
    tf destroy -auto-approve -input=false
    tf_read state "$LAB_DIR/remaining" list
    [[ ! -s "$LAB_DIR/remaining" ]] || die "Lab state is not empty: $TF_VAR_run_id"
    bash "$IAC_ROOT/scripts/pipeline/xconnect-lab-lease.sh" delete
    echo "Destroyed lab $TF_VAR_run_id; remote state retained for audit."
    ;;
esac
