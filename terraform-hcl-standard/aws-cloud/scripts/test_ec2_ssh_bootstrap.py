#!/usr/bin/env python3
"""Contract check for EC2 SSH service bootstrap user data."""

import pathlib


module = pathlib.Path(__file__).resolve().parents[1] / "modules/ec2/main.tf"
source = module.read_text()

assert "systemctl enable --now ssh || systemctl enable --now sshd || true" in source
assert "var.max_runtime_minutes > 0 ? format(" in source
assert "/sbin/shutdown -h now" in source
assert "user_data_replace_on_change = var.spot_instance" in source
assert ") : null" not in source.split("user_data =", 1)[1].split("subnet_id", 1)[0]

print("test_ec2_ssh_bootstrap: PASS")
