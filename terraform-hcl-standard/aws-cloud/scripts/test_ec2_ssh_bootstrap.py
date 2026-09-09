#!/usr/bin/env python3
"""Contract check for EC2 SSH service bootstrap user data."""

import pathlib


module = pathlib.Path(__file__).resolve().parents[1] / "modules/ec2/main.tf"
source = module.read_text()

assert "apt-get install -y -qq openssh-server" in source
assert "install -d -m 0755 /run/sshd" in source
assert "90-ai-workspace-port.conf" in source
assert "var.ssh_port" in source
assert "ssh-keygen -A" in source
assert "sshd -t" in source
assert "systemctl restart ssh.service || systemctl restart sshd.service || true" in source
assert "/usr/sbin/sshd" in source
assert "var.max_runtime_minutes > 0 ? format(" in source
assert '# capacity-mode: %s' in source
assert 'var.spot_instance ? "spot" : "on-demand"' in source
assert "/sbin/shutdown -h now" in source
assert "user_data_replace_on_change = var.max_runtime_minutes > 0" in source
assert ") : null" in source.split("user_data =", 1)[1].split("subnet_id", 1)[0]

print("test_ec2_ssh_bootstrap: PASS")
