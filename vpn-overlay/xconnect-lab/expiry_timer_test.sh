#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT

render_bootstrap() {
  local expires_at=$1
  local role=$2
  sed \
    -e 's|\$\${expires_at}|__SHELL_EXPIRES_AT__|g' \
    -e "s|\\\${role}|${role}|g" \
    -e 's|\${run_id}|xcl-shell-test-1|g' \
    -e 's|\${ssh_public_key}|ssh-ed25519 TESTKEY|g' \
    -e "s|\${expires_at}|${expires_at}|g" \
    -e 's|\$\${|${|g' \
    -e 's|__SHELL_EXPIRES_AT__|${expires_at}|g' \
    "${root}/bootstrap.sh"
}

cat > "${work}/systemctl" <<'SYSTEMCTL'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${XCONNECT_LAB_TEST_ROOT}/systemctl.log"
SYSTEMCTL
chmod 0755 "${work}/systemctl"

cat > "${work}/poweroff" <<'POWEROFF'
#!/usr/bin/env bash
set -euo pipefail
printf 'poweroff\n' >> "${XCONNECT_LAB_TEST_ROOT}/poweroff.log"
POWEROFF
chmod 0755 "${work}/poweroff"

mkdir -p "${work}/bin"
cat > "${work}/bin/date" <<'DATE'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-u" && "${2:-}" == "-d" ]]; then
  # The real bootstrap runs on Linux; this fixture only supplies the GNU-date
  # operations that the macOS test host does not provide.
  case "${3:-}" in
    2099-01-02T03:04:05Z)
      case "${4:-}" in
        +%s) printf '4071006245\n' ;;
        '+%Y-%m-%d %H:%M:%S UTC') printf '2099-01-02 03:04:05 UTC\n' ;;
      esac
      ;;
    2000-01-02T03:04:05Z)
      case "${4:-}" in
        +%s) printf '946782245\n' ;;
        '+%Y-%m-%d %H:%M:%S UTC') printf '2000-01-02 03:04:05 UTC\n' ;;
      esac
      ;;
    @4071006245)
      [[ "${4:-}" == "+%Y-%m-%dT%H:%M:%SZ" ]] && printf '2099-01-02T03:04:05Z\n'
      ;;
    @946782245)
      [[ "${4:-}" == "+%Y-%m-%dT%H:%M:%SZ" ]] && printf '2000-01-02T03:04:05Z\n'
      ;;
  esac
elif [[ "${1:-}" == "-u" && "${2:-}" == "+%s" ]]; then
  # Fixed test clock: after the expired fixture and before the future fixture.
  printf '1800000000\n'
else
  exit 1
fi
DATE
chmod 0755 "${work}/bin/date"

cat > "${work}/sysctl" <<'SYSCTL'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${XCONNECT_LAB_TEST_ROOT}/sysctl.log"
SYSCTL
chmod 0755 "${work}/sysctl"

future_root="${work}/future"
mkdir -p "${future_root}"
render_bootstrap "2099-01-02T03:04:05Z" controlled-client > "${work}/future-bootstrap.sh"
chmod 0755 "${work}/future-bootstrap.sh"
XCONNECT_LAB_TEST_ROOT="${future_root}" \
XCONNECT_LAB_TEST_SYSTEMCTL="${work}/systemctl" \
XCONNECT_LAB_TEST_POWEROFF="${work}/poweroff" \
XCONNECT_LAB_TEST_SYSCTL="${work}/sysctl" \
PATH="${work}/bin:${PATH}" \
"${work}/future-bootstrap.sh"

grep -Fxq 'daemon-reload' "${future_root}/systemctl.log"
grep -Fxq 'enable --now xconnect-lab-expiry.timer' "${future_root}/systemctl.log"
grep -Fxq 'OnCalendar=2099-01-02 03:04:05 UTC' "${future_root}/etc/systemd/system/xconnect-lab-expiry.timer"
grep -Fxq 'AccuracySec=1s' "${future_root}/etc/systemd/system/xconnect-lab-expiry.timer"
grep -Fxq 'Persistent=true' "${future_root}/etc/systemd/system/xconnect-lab-expiry.timer"
grep -Fxq 'ExecStart=/sbin/poweroff' "${future_root}/etc/systemd/system/xconnect-lab-expiry.service"
[[ ! -e "${future_root}/poweroff.log" ]]

if command -v systemd-analyze >/dev/null 2>&1; then
  systemd-analyze calendar '2099-01-02 03:04:05 UTC' >/dev/null
fi

relay_root="${work}/relay"
mkdir -p "${relay_root}"
render_bootstrap "2099-01-02T03:04:05Z" relay > "${work}/relay-bootstrap.sh"
chmod 0755 "${work}/relay-bootstrap.sh"
XCONNECT_LAB_TEST_ROOT="${relay_root}" \
XCONNECT_LAB_TEST_SYSTEMCTL="${work}/systemctl" \
XCONNECT_LAB_TEST_POWEROFF="${work}/poweroff" \
XCONNECT_LAB_TEST_SYSCTL="${work}/sysctl" \
PATH="${work}/bin:${PATH}" \
"${work}/relay-bootstrap.sh"

grep -Fxq -- '--system' "${relay_root}/sysctl.log"
grep -Fxq 'net.ipv4.ip_forward=1' "${relay_root}/etc/sysctl.d/99-xconnect-relay.conf"
grep -Fxq 'net.ipv4.conf.all.src_valid_mark=1' "${relay_root}/etc/sysctl.d/99-xconnect-relay.conf"
grep -Fxq 'OnCalendar=2099-01-02 03:04:05 UTC' "${relay_root}/etc/systemd/system/xconnect-lab-expiry.timer"

expired_root="${work}/expired"
mkdir -p "${expired_root}"
render_bootstrap "2000-01-02T03:04:05Z" relay > "${work}/expired-bootstrap.sh"
chmod 0755 "${work}/expired-bootstrap.sh"
XCONNECT_LAB_TEST_ROOT="${expired_root}" \
XCONNECT_LAB_TEST_SYSTEMCTL="${work}/systemctl" \
XCONNECT_LAB_TEST_POWEROFF="${work}/poweroff" \
XCONNECT_LAB_TEST_SYSCTL="${work}/sysctl" \
PATH="${work}/bin:${PATH}" \
"${work}/expired-bootstrap.sh"

grep -Fxq 'poweroff' "${expired_root}/poweroff.log"
[[ ! -e "${expired_root}/etc/systemd/system/xconnect-lab-expiry.timer" ]]

echo 'XConnect expiry bootstrap installs an absolute persistent timer and powers off immediately when expired.'
