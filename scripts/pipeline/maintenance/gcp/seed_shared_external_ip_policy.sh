#!/usr/bin/env bash
# One-time, organization-admin bootstrap for a shared GCP project's external
# IPv4 allowlist. The desired policy comes only from the GitOps manifest.
# IaC owner: migrated from Platform-Orchestrator scripts/cloud/bootstrap/gcp (org policy = cloud IAM).
set -euo pipefail

usage() {
  echo 'usage: seed_shared_external_ip_policy.sh --manifest GITOPS_YAML [--render|--apply]' >&2
  exit 2
}

manifest=''
action=render
while (($#)); do
  case "$1" in
    --manifest) (($# >= 2)) || usage; manifest="$2"; shift 2 ;;
    --render) action=render; shift ;;
    --apply) action=apply; shift ;;
    *) usage ;;
  esac
done
[[ -f "${manifest}" ]] || usage
command -v ruby >/dev/null || { echo 'ruby is required' >&2; exit 1; }

policy_file="$(mktemp)"
token_file=''
error_file=''
cleanup() {
  [[ -z "${token_file}" ]] || rm -f -- "${token_file}"
  [[ -z "${error_file}" ]] || rm -f -- "${error_file}"
  rm -f -- "${policy_file}"
}
trap cleanup EXIT

ruby -ryaml -rjson -e '
  doc = YAML.safe_load(File.read(ARGV.fetch(0)))
  abort "expected a shared GCPWorkloadNamespace" unless
    doc.dig("kind") == "GCPWorkloadNamespace" &&
    doc.dig("metadata", "environment") == "shared" &&
    doc.dig("metadata", "provider") == "gcp"
  spec = doc.fetch("spec")
  project = spec.fetch("project_id")
  account = spec.fetch("gcp_account_id").to_s
  abort "invalid logical GCP account id" unless account.match?(/\A[A-Za-z0-9][A-Za-z0-9._%+@-]{0,126}[A-Za-z0-9]\z/)
  abort "invalid GCP project ID" unless project.match?(/\A[a-z][a-z0-9-]{4,28}[a-z0-9]\z/)
  instances = spec.fetch("external_ip_allowed_instances")
  abort "empty external IP allowlist" unless instances.is_a?(Array) && !instances.empty?
  values = instances.map do |instance|
    name = instance.fetch("name")
    zone = instance.fetch("zone")
    abort "invalid instance name or zone" unless
      name.match?(/\A[a-z][a-z0-9-]*[a-z0-9]\z/) &&
      zone.match?(/\A[a-z]+-[a-z]+[0-9]+-[a-z]\z/)
    "projects/#{project}/zones/#{zone}/instances/#{name}"
  end
  abort "duplicate allowlist entry" unless values.uniq.length == values.length
  puts JSON.pretty_generate({name: "projects/#{project}/policies/compute.vmExternalIpAccess",
                             spec: {rules: [{values: {allowedValues: values}}]}})
' "${manifest}" >"${policy_file}"

project_id="$(ruby -rjson -e 'puts JSON.parse(File.read(ARGV.fetch(0))).fetch("name").split("/")[1]' "${policy_file}")"
if [[ "${action}" == render ]]; then
  printf 'GitOps-derived project policy for %s:\n' "${project_id}"
  ruby -rjson -e 'puts JSON.pretty_generate(JSON.parse(File.read(ARGV.fetch(0))))' "${policy_file}"
  exit 0
fi

command -v gcloud >/dev/null || { echo 'gcloud is required for --apply' >&2; exit 1; }
command -v jq >/dev/null || { echo 'jq is required for --apply' >&2; exit 1; }
umask 077
token_file="$(mktemp)"
error_file="$(mktemp)"
gcloud auth application-default print-access-token >"${token_file}"

if gcloud --access-token-file="${token_file}" --billing-project="${project_id}" org-policies describe \
  compute.vmExternalIpAccess --project="${project_id}" --format=json \
  >"${error_file}" 2>&1; then
  current="$(jq -c '.spec.rules[0].values.allowedValues // [] | sort' "${error_file}")"
  desired="$(jq -c '.spec.rules[0].values.allowedValues | sort' "${policy_file}")"
  if [[ "${current}" != "${desired}" ]]; then
    echo 'Existing project policy differs from GitOps; refusing to overwrite. Review it manually.' >&2
    exit 1
  fi
  echo "${project_id}: external IP policy already matches GitOps."
elif grep -Fq 'NOT_FOUND' "${error_file}"; then
  gcloud --access-token-file="${token_file}" --billing-project="${project_id}" org-policies set-policy "${policy_file}" --quiet
  echo "${project_id}: GitOps external IP policy created."
else
  sed -n '1,8p' "${error_file}" >&2
  exit 1
fi
