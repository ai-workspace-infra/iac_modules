#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
export PATH="$tmp/bin:$PATH" MOCK_ROOT="$tmp" VAULT_ADDR=https://vault.svc.plus VAULT_TOKEN=fixture-token VAULT_ENV_PATH=uat GCP_PROJECT_ID=open-platform-uat GITHUB_OUTPUT="$tmp/output"
cat > "$tmp/bin/curl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
while (( $# )); do case "$1" in -o) output="$2"; shift 2 ;; -H|--max-time|-w) shift 2 ;; *) shift ;; esac; done
echo '{"data":{"data":{"username":"fixture-user","password":"fixture-password"}}}' > "$output"
printf '%s' "${MOCK_HTTP:-200}"
MOCK
cat > "$tmp/bin/gcloud" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
echo "$1 $2 $3" >> "$MOCK_ROOT/calls"
case "$1 $2 $3" in
  'secrets describe smtp-username'|'secrets describe smtp-password') exit 1 ;;
  'secrets create smtp-username'|'secrets create smtp-password') [[ "${MOCK_FAILURE:-}" != create ]] ;;
  'secrets versions add')
    name="$4"; shift 4
    for argument in "$@"; do case "$argument" in --data-file=*) cp "${argument#--data-file=}" "$MOCK_ROOT/$name" ;; esac; done ;;
  'secrets versions access')
    for argument in "$@"; do case "$argument" in --secret=*) name="${argument#--secret=}" ;; esac; done
    if [[ "${MOCK_FAILURE:-}" == convergence ]]; then printf wrong; else cat "$MOCK_ROOT/$name"; fi ;;
  *) exit 2 ;;
esac
MOCK
chmod 755 "$tmp/bin/"*
fixture() { rm -f "$tmp/output" "$tmp/calls" "$tmp/smtp-username" "$tmp/smtp-password"; }
reject() { if bash "$root/sync-smtp-secrets.sh" >/dev/null 2>&1; then exit 1; fi; [[ ! -s "$GITHUB_OUTPUT" ]]; echo "PASS reject $1"; }
fixture; MOCK_HTTP=404 bash "$root/sync-smtp-secrets.sh" >/dev/null; grep -q '^smtp_configured=false$' "$GITHUB_OUTPUT"; [[ ! -e "$tmp/calls" ]]; echo 'PASS explicit absent source makes no Provider call'
fixture; bash "$root/sync-smtp-secrets.sh" >/dev/null; grep -q '^smtp_configured=true$' "$GITHUB_OUTPUT"; echo 'PASS configured SMTP secrets converge'
fixture; MOCK_FAILURE=create reject 'Provider permission failure'
fixture; MOCK_FAILURE=convergence reject 'written secret failed readback'
fixture; MOCK_HTTP=401 reject 'Vault credential rejection'
echo '5 SMTP owner checks passed using mock Vault/Provider responses.'
