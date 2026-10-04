#!/usr/bin/env bash
set -euo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/vultr-instance-snapshot.sh"
tmp="$(mktemp -d)"
trap 'rm -r "${tmp}"' EXIT

mkdir -p "${tmp}/bin"
cat > "${tmp}/bin/curl" <<'CURL'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${CALL_LOG}"
if [[ "$*" == *' -X POST '* ]]; then
  printf '{"snapshot":{"id":"snap-123"}}\n'
  exit 0
fi
count="$(cat "${READ_COUNT}" 2>/dev/null || echo 0)"
count="$((count + 1))"
printf '%s\n' "${count}" > "${READ_COUNT}"
case "${FAKE_STATUS:-complete}" in
  pending-then-complete)
    if (( count == 1 )); then printf '{"snapshot":{"status":"pending"}}\n'; else printf '{"snapshot":{"status":"complete"}}\n'; fi ;;
  error) printf '{"snapshot":{"status":"error"}}\n' ;;
  pending) printf '{"snapshot":{"status":"pending"}}\n' ;;
  *) printf '{"snapshot":{"status":"complete"}}\n' ;;
esac
CURL
cat > "${tmp}/bin/sleep" <<'SLEEP'
#!/usr/bin/env bash
exit 0
SLEEP
chmod +x "${tmp}/bin/curl" "${tmp}/bin/sleep"
export PATH="${tmp}/bin:${PATH}" CALL_LOG="${tmp}/calls" READ_COUNT="${tmp}/count"
export VULTR_API_KEY='test-only' INSTANCE_ID='instance-123' VULTR_SNAPSHOT_WAIT_ATTEMPTS=2 VULTR_SNAPSHOT_WAIT_INTERVAL_SECONDS=0

GITHUB_OUTPUT="${tmp}/output" FAKE_STATUS=pending-then-complete "${script}"
grep -qx 'snapshot_id=snap-123' "${tmp}/output"
[[ "$(grep -c -- '-X POST' "${CALL_LOG}")" == 1 ]]
[[ "$(cat "${READ_COUNT}")" == 2 ]]

: > "${CALL_LOG}"
: > "${tmp}/output"
printf 0 > "${READ_COUNT}"
GITHUB_OUTPUT="${tmp}/output" VULTR_SNAPSHOT_ID=snap-existing "${script}"
grep -qx 'snapshot_id=snap-existing' "${tmp}/output"
! grep -q -- '-X POST' "${CALL_LOG}"

printf 0 > "${READ_COUNT}"
if FAKE_STATUS=error "${script}" > "${tmp}/stdout" 2> "${tmp}/stderr"; then exit 1; fi
grep -q 'reported snapshot failure' "${tmp}/stderr"

printf 0 > "${READ_COUNT}"
if FAKE_STATUS=pending "${script}" > "${tmp}/stdout" 2> "${tmp}/stderr"; then exit 1; fi
grep -q 'did not complete' "${tmp}/stderr"

if VULTR_SNAPSHOT_WAIT_ATTEMPTS=0 "${script}" > "${tmp}/stdout" 2> "${tmp}/stderr"; then exit 1; fi
grep -q 'attempts must be positive' "${tmp}/stderr"

echo 'vultr snapshot executor contract: PASS'
