#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
export RUNNER_TEMP="$tmp" RESOURCE_ENVIRONMENT=uat EXISTING_TARGET_HOST=dynamic.example.org EXISTING_TARGET_USER=operator
export EXISTING_HOST_DECLARATION="$tmp/declaration" OUTPUT_DIR="$tmp/cmdb"
printf 'kind: ExistingHostDeclaration\nmetadata: {name: uat-existing, environment: uat}\nspec: {management_mode: existing, fact_source: explicit-target, groups: [ai_workspace], service_domains: [service.example.org], xconnect_required: true}\n' > "$EXISTING_HOST_DECLARATION"
bash "$root/render-existing-host-cmdb.sh" >/dev/null
jq -e '.["dynamic.example.org"] | .ansible_user == "operator" and .fact_source == "explicit-target" and
  (has("provider") or has("region") or has("instance_id") or has("plan") | not)' "$OUTPUT_DIR/cmdb.json" >/dev/null
echo 'PASS explicit dynamic target without fabricated Provider facts'
if RESOURCE_ENVIRONMENT=prod OUTPUT_DIR="$tmp/prod" bash "$root/render-existing-host-cmdb.sh" >/dev/null 2>&1; then exit 1; fi
echo 'PASS reject existing target outside UAT'
cat > "$tmp/bin/curl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
output= url=
while (( $# )); do
  case "$1" in -o) output="$2"; shift 2 ;; -H|--retry|--max-time|-w) shift 2 ;; http*) url="$1"; shift ;; *) shift ;; esac
done
case "$url" in
  */instances/stale-id) echo '{}' > "$output"; printf 404 ;;
  *'/instances?'*) if [[ "${AMBIGUOUS:-false}" == true ]]; then
    echo '{"instances":[{"id":"new-id","label":"service.example.org"},{"id":"other-id","label":"service.example.org"}]}';
    else echo '{"instances":[{"id":"new-id","label":"service.example.org"}]}'; fi ;;
  */instances/new-id) echo '{"instance":{"plan":"vc2-1c-1gb","region":"nrt","os_id":1743,"main_ip":"198.51.100.7","label":"service.example.org","vcpu_count":1,"ram":1024,"disk":25}}' > "$output"; printf 200 ;;
  *'/plans?'*) echo '{"plans":[{"id":"vc2-2c-2gb","vcpu_count":2,"ram":2048,"disk":55}]}' ;;
  *) exit 2 ;;
esac
MOCK
chmod 755 "$tmp/bin/curl"
export PATH="$tmp/bin:$PATH" VULTR_API_KEY=fixture-key INSTANCE_ID=stale-id TARGET_PLAN=vc2-2c-2gb EXPECTED_HOSTNAME=service.example.org GITHUB_OUTPUT="$tmp/output"
bash "$root/resize-instance-preflight.sh" >/dev/null 2>&1
rg -q '^instance_id=new-id$' "$GITHUB_OUTPUT"; rg -q '^direction=upgrade$' "$GITHUB_OUTPUT"
echo 'PASS authoritative resolved ID emitted for downstream operations'
rm "$GITHUB_OUTPUT"
if AMBIGUOUS=true bash "$root/resize-instance-preflight.sh" >/dev/null 2>&1; then exit 1; fi
[[ ! -s "$GITHUB_OUTPUT" ]]; echo 'PASS reject ambiguous Provider selector'
echo '4 resource fact checks passed with no Provider connection.'
