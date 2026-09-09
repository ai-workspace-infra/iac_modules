#!/usr/bin/env python3
"""Contract check for the production Agent Proxy public ingress declaration."""

import os
import pathlib
import re
import sys

import yaml
from jinja2 import Environment, FileSystemLoader


root = pathlib.Path(__file__).resolve().parents[1]
config = root / "config/resources/prod/agent-proxy.yaml"
template_dir = root / "templates"

os.environ.setdefault("TARGET_DOMAIN_BASE", "svc.plus")
os.environ.setdefault("SSH_PUBLIC_DEPLOY_KEY", "ssh-ed25519 AAAAcontract")
from jinja2 import Template

data = yaml.safe_load(Template(config.read_text()).render(env=os.environ))
assert data["global"]["aws_us_region"] == "us-west-2"
assert data["global"]["aws_hk_region"] == "ap-southeast-1"
host = next(item for item in data["hosts"] if item["name"] == "agent-proxy-node-prod")
assert host["node_id"] == "ap-prod-tky"
assert host["short_hostname"] == "ap-prod-tky"
assert host["display_name"] == "ap-prod-tky (tky-on-demand)"
assert host["cloud_provider"] == "aws"
assert host["cloud_region"] == "ap-northeast-1"
assert host["location"] == "tky"
assert host["node_label"] == "tky-on-demand"
assert host["plan"] == "t4g.micro"
rules = host.get("security_group_ingress", [])
assert {(
    rule["port"], rule["protocol"], rule["cidr"]
) for rule in rules} >= {(1443, "tcp", "0.0.0.0/0")}

environment = Environment(loader=FileSystemLoader(template_dir))
environment.filters["tf_id"] = lambda value: re.sub(r"[^0-9a-zA-Z_]", "_", str(value))
template = environment.get_template("hosts.tf.j2")
rendered = template.render(ssh_keys=data["ssh_keys"], hosts=data["hosts"], true=True, false=False)
assert 'from_port   = 1443' in rendered
assert 'to_port     = 1443' in rendered
assert 'protocol    = "tcp"' in rendered
assert 'cidr_blocks = ["0.0.0.0/0"]' in rendered
assert 'name_prefix = var.name_prefix != "" ? "${var.name_prefix}-ap-prod-tky"' in rendered

us_host = next(item for item in data["hosts"] if item["name"] == "agent-proxy-node-prod-us")
assert us_host["node_id"] == "ap-prod-us"
assert us_host["short_hostname"] == "ap-prod-us"
assert us_host["display_name"] == "ap-prod-us (us-spot)"
assert us_host["cloud_provider"] == "aws"
assert us_host["cloud_region"] == "us-west-2"
assert us_host["location"] == "us"
assert us_host["node_label"] == "us-spot"
assert us_host["plan"] == "t4g.micro"
assert us_host["aws_provider"] == "us"
assert us_host["aws_region"] == "us-west-2"
assert "availability_zone" not in us_host
assert us_host["spot_instance"] is True
assert us_host["max_runtime_minutes"] == 60
assert us_host["elastic_ip"] is False
assert "agent-proxy-selfhost-prod-us.svc.plus" in us_host["host_vars"]["service_domains"]
assert 'resource "aws_key_pair" "ai_workspace_admin"' in rendered
assert 'resource "aws_key_pair" "key_agent_proxy_node_prod_us_ai_workspace_admin"' in rendered
assert "provider = aws.us" in rendered
assert "spot_instance       = true" in rendered
assert "max_runtime_minutes = 60" in rendered
assert "subnet_id           = null" in rendered
assert 'values = ["debian-13-arm64-*", "debian-12-arm64-*"]' in rendered
assert 'name_prefix = var.name_prefix != "" ? "${var.name_prefix}-ap-prod-us"' in rendered

hk_host = next(item for item in data["hosts"] if item["name"] == "agent-proxy-node-prod-hk")
assert hk_host["node_id"] == "ap-prod-hk"
assert hk_host["location"] == "hk"
assert hk_host["aws_provider"] == "hk"
assert hk_host["cloud_region"] == "ap-southeast-1"
assert hk_host["aws_region"] == "ap-southeast-1"
assert "ssh_port" not in hk_host
assert hk_host["spot_instance"] is True
assert hk_host["max_runtime_minutes"] == 60
assert hk_host["elastic_ip"] is False
assert "agent-proxy-selfhost-prod-hk.svc.plus" in hk_host["host_vars"]["service_domains"]
assert 'resource "aws_key_pair" "key_agent_proxy_node_prod_hk_ai_workspace_admin"' in rendered
assert "provider = aws.hk" in rendered
assert "from_port   = 22" in rendered
assert "ssh_port            = 22" in rendered
assert 'name_prefix = var.name_prefix != "" ? "${var.name_prefix}-ap-prod-hk"' in rendered

print("test_prod_agent_proxy_security_group: PASS")
