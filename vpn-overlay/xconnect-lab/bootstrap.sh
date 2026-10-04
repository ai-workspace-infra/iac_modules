#!/usr/bin/env bash
set -euo pipefail

expires_at='${expires_at}'
if [[ ! "$${expires_at}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]]; then
  echo "xconnect-lab: expires_at must be absolute RFC3339 UTC" >&2
  exit 1
fi
if ! expiry_epoch=$(date -u -d "$${expires_at}" +%s 2>/dev/null); then
  echo "xconnect-lab: expires_at is not a valid UTC timestamp" >&2
  exit 1
fi
if [[ "$(date -u -d "@$${expiry_epoch}" +%Y-%m-%dT%H:%M:%SZ)" != "$${expires_at}" ]]; then
  echo "xconnect-lab: expires_at is not a canonical UTC timestamp" >&2
  exit 1
fi

test_root="$${XCONNECT_LAB_TEST_ROOT:-}"
systemctl_bin="$${XCONNECT_LAB_TEST_SYSTEMCTL:-systemctl}"
poweroff_bin="$${XCONNECT_LAB_TEST_POWEROFF:-/sbin/poweroff}"
if [[ -n "$${test_root}" ]]; then
  etc_root="$${test_root}/etc"
  home_root="$${test_root}/home/ubuntu"
  sysctl_root="$${etc_root}/sysctl.d"
  sysctl_bin="$${XCONNECT_LAB_TEST_SYSCTL:-sysctl}"
else
  etc_root="/etc"
  home_root="/home/ubuntu"
  sysctl_root="/etc/sysctl.d"
  sysctl_bin="sysctl"
fi

if (( expiry_epoch <= $(date -u +%s) )); then
  "$${poweroff_bin}"
  exit 0
fi

expiry_calendar=$(date -u -d "$${expires_at}" '+%Y-%m-%d %H:%M:%S UTC')
install -d -m 0755 "$${etc_root}/systemd/system"
cat > "$${etc_root}/systemd/system/xconnect-lab-expiry.service" <<'UNIT'
[Unit]
Description=Power off the disposable XConnect lab at its absolute expiry

[Service]
Type=oneshot
ExecStart=/sbin/poweroff
UNIT

cat > "$${etc_root}/systemd/system/xconnect-lab-expiry.timer" <<UNIT
[Unit]
Description=Absolute expiry for the disposable XConnect lab

[Timer]
OnCalendar=$${expiry_calendar}
AccuracySec=1s
Persistent=true
Unit=xconnect-lab-expiry.service

[Install]
WantedBy=timers.target
UNIT
"$${systemctl_bin}" daemon-reload
"$${systemctl_bin}" enable --now xconnect-lab-expiry.timer

install -d -m 0755 "$${etc_root}/xconnect-lab"
printf '%s\n' '${role}' > "$${etc_root}/xconnect-lab/node-role"
printf '%s\n' '${run_id}' > "$${etc_root}/xconnect-lab/lab-run"
chmod 0644 "$${etc_root}/xconnect-lab/node-role" "$${etc_root}/xconnect-lab/lab-run"

# Scope the generated SSH credential to this instance instead of creating a
# persistent EC2 key-pair resource in the reused UAT account.
if [[ -n "$${test_root}" ]]; then
  install -d -m 0700 "$${home_root}/.ssh"
  printf '%s\n' '${ssh_public_key}' > "$${home_root}/.ssh/authorized_keys"
  chmod 0600 "$${home_root}/.ssh/authorized_keys"
else
  install -d -o ubuntu -g ubuntu -m 0700 "$${home_root}/.ssh"
  printf '%s\n' '${ssh_public_key}' > "$${home_root}/.ssh/authorized_keys"
  chown ubuntu:ubuntu "$${home_root}/.ssh/authorized_keys"
  chmod 0600 "$${home_root}/.ssh/authorized_keys"
fi

if [[ '${role}' == 'relay' ]]; then
  install -d -m 0755 "$${sysctl_root}"
  cat > "$${sysctl_root}/99-xconnect-relay.conf" <<'SYSCTL'
net.ipv4.ip_forward=1
net.ipv4.conf.all.src_valid_mark=1
SYSCTL
  "$${sysctl_bin}" --system >/dev/null
fi

touch "$${etc_root}/xconnect-lab/bootstrap.ready"
