#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${EXISTING_HOST_DECLARATION:?}" "${EXISTING_TARGET_HOST:?}" "${EXISTING_TARGET_USER:?}" "${OUTPUT_DIR:?}" "${RESOURCE_ENVIRONMENT:?}"
[[ "$RESOURCE_ENVIRONMENT" == uat ]] || { echo 'Existing AI Workspace target is UAT-only' >&2; exit 2; }
[[ "$EXISTING_TARGET_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$ &&
   "$EXISTING_TARGET_USER" =~ ^[a-z_][a-z0-9_-]{0,31}\$?$ ]] || exit 2
declaration="$(mktemp)"
trap 'rm -f "$declaration"' EXIT
yq -o=json '.' "$EXISTING_HOST_DECLARATION" > "$declaration"
jq -e --arg environment "$RESOURCE_ENVIRONMENT" '
  .kind == "ExistingHostDeclaration" and .metadata.environment == $environment and
  .spec.management_mode == "existing" and .spec.fact_source == "explicit-target" and
  (.spec.groups | type == "array" and length > 0 and all(.[]; test("^[a-z][a-z0-9_]*$"))) and
  (.spec.service_domains | type == "array" and all(.[]; test("^[A-Za-z0-9][A-Za-z0-9.-]+$")))' "$declaration" >/dev/null
mkdir -p "$OUTPUT_DIR"
# An explicit externally managed target is not a verified provider instance.
# Do not invent instance ID, capacity, cloud provider, region or Terraform state.
jq --arg host "$EXISTING_TARGET_HOST" --arg user "$EXISTING_TARGET_USER" '
  . as $d | {name:$d.metadata.name,fqdn:$host,ip:$host,ansible_user:$user,groups:$d.spec.groups,
    fact_source:"explicit-target",host_vars:{management_mode:"existing",fact_source:"explicit-target",
      service_domains:$d.spec.service_domains,xconnect_required:$d.spec.xconnect_required}} as $record |
  {($host):$record}' "$declaration" > "$OUTPUT_DIR/cmdb.json"
jq --arg environment "$RESOURCE_ENVIRONMENT" '{environment:$environment,management_mode:"existing",fact_source:"explicit-target",hosts:[.[]]}' \
  "$OUTPUT_DIR/cmdb.json" > "$OUTPUT_DIR/hosts_manifest.json"
while IFS= read -r group; do
  printf '[%s]\n%s ansible_host=%s ansible_user=%s management_mode=existing\n\n' \
    "$group" "$EXISTING_TARGET_HOST" "$EXISTING_TARGET_HOST" "$EXISTING_TARGET_USER"
done < <(jq -r '.spec.groups[]' "$declaration") > "$OUTPUT_DIR/inventory.ini"
chmod 600 "$OUTPUT_DIR/cmdb.json" "$OUTPUT_DIR/hosts_manifest.json" "$OUTPUT_DIR/inventory.ini"
echo 'IaC rendered explicit existing-target inventory; no provider facts fabricated.'
