#!/usr/bin/env bash
# UAT offline checks: no Guance workspace, Vault or credentials required.
#   offline-check.sh [--manifest PATH]    (default: tests/fixtures/uat-observability.yaml)
# Proves: unit contracts, explicit HCL (no loops), terraform fmt/validate against the pinned
# provider schema, no credential-shaped content in sources or rendered output.
# It does NOT prove anything about a real workspace (endpoint, API permissions, queries, alerts).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
manifest="$root/tests/fixtures/uat-observability.yaml"
if [[ "${1:-}" == --manifest ]]; then manifest="${2:?}"; fi
tf="${TERRAFORM:-terraform}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

step() { printf '== %s\n' "$1"; }

step 'unit and contract tests'
python3 -m unittest discover -s "$root/tests"

step 'render manifest'
python3 "$here/generate.py" render --resources "$manifest" --workdir "$work"

step 'no HCL loops or template control flow (templates and rendered)'
python3 "$here/hcl_policy.py" "$work" "$root/templates"

step 'terraform fmt / init / validate (pinned provider, no backend)'
"$tf" -chdir="$work" fmt -check -diff -no-color
"$tf" -chdir="$work" init -backend=false -input=false -no-color >/dev/null
"$tf" -chdir="$work" validate -no-color

step 'no credential-shaped content in sources or rendered output'
python3 "$here/secret_scan.py" "$root" "$work"

step 'shell syntax'
for script in "$here"/*.sh; do bash -n "$script"; done
if command -v shellcheck >/dev/null; then shellcheck -x "$here"/*.sh; else printf 'shellcheck not installed; skipped\n'; fi

step 'rendered artifacts are git-ignored'
for artifact in generated_resources.tf terraform.auto.tfvars.json cmdb.json generated_imports.tf; do
  git -C "$root" check-ignore -q "envs/uat/$artifact" || { printf '%s is not ignored\n' "$artifact" >&2; exit 1; }
done
printf 'OFFLINE CHECKS PASSED (offline only; real workspace acceptance is separate)\n'
