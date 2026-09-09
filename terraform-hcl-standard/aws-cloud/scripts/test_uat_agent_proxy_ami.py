#!/usr/bin/env python3
"""Contract check for regional UAT Agent Proxy AMI selection."""

import os
import pathlib
import re

import yaml
from jinja2 import Environment, FileSystemLoader, Template


root = pathlib.Path(__file__).resolve().parents[1]
config = root / "config/resources/uat/agent-proxy.yaml"
template_dir = root / "templates"

os.environ.setdefault("TARGET_DOMAIN_BASE", "onwalk.net")
os.environ.setdefault("SSH_PUBLIC_DEPLOY_KEY", "ssh-ed25519 AAAAcontract")

data = yaml.safe_load(Template(config.read_text()).render(env=os.environ))
hk_host = next(
    item for item in data["hosts"] if item["name"] == "agent-proxy-node-uat-hk"
)

assert hk_host["aws_provider"] == "hk"
assert hk_host["aws_region"] == "ap-east-1"
assert hk_host["ansible_user"] == "admin"
assert "ami_id" not in hk_host
assert hk_host["ami_name_patterns"] == ["debian-12-arm64-*"]
assert hk_host["os_name"].startswith("Debian 12 ARM64")
assert hk_host["billing_mode"] == "on_demand"
assert hk_host["spot_instance"] is False
assert hk_host["max_runtime_minutes"] == 60

environment = Environment(loader=FileSystemLoader(template_dir))
environment.filters["tf_id"] = lambda value: re.sub(
    r"[^0-9a-zA-Z_]", "_", str(value)
)
rendered = environment.get_template("hosts.tf.j2").render(
    ssh_keys=data["ssh_keys"], hosts=data["hosts"], true=True, false=False
)

assert 'data "aws_ami" "debian_agent_proxy_node_uat_hk"' in rendered
hk_lookup = rendered.split(
    'data "aws_ami" "debian_agent_proxy_node_uat_hk"', 1
)[1].split("resource", 1)[0]
assert 'values = ["debian-12-arm64-*"]' in hk_lookup
assert "debian-13-arm64-*" not in hk_lookup
assert "ami  = data.aws_ami.debian_agent_proxy_node_uat_hk.id" in rendered

print("test_uat_agent_proxy_ami: PASS")
