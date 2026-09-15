#!/usr/bin/env python3
"""Render the declarative GCP AI Aggregator UAT contract.

The script intentionally expands every host into an explicit Terraform module
block. Runtime addresses are merged into a non-sensitive Ansible inventory;
Vault values never pass through this renderer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
TEMPLATE_DIR = ROOT / "templates"


def tf_id(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]", "_", str(value))


def load_contract(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    global_cfg = data.get("global", {})
    required = ["provider", "environment", "project_id_env", "region", "subnet_cidr", "image"]
    missing = [key for key in required if not global_cfg.get(key)]
    if missing:
        raise SystemExit(f"contract missing global field(s): {', '.join(missing)}")
    if global_cfg["provider"] != "gcp" or global_cfg["environment"] != "uat":
        raise SystemExit("this renderer only accepts the GCP UAT contract")
    if global_cfg.get("lifecycle") != "ephemeral" or not global_cfg.get("spot_instance"):
        raise SystemExit("GCP UAT must be ephemeral Spot")
    if global_cfg.get("max_runtime_minutes") != 60:
        raise SystemExit("GCP UAT max_runtime_minutes must be 60")
    hosts = global_cfg.get("hosts", [])
    if len(hosts) != 5 or {host.get("role") for host in hosts} != {"gateway", "cpa"}:
        raise SystemExit("GCP UAT contract must contain one gateway and four CPA hosts")
    ids = [host.get("id") for host in hosts]
    if len(ids) != len(set(ids)) or not all(ids):
        raise SystemExit("host ids must be unique and non-empty")
    return data


def renderer(contract: dict) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        trim_blocks=True,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    env.filters["tf_id"] = tf_id
    return env


def render(args: argparse.Namespace) -> None:
    contract = load_contract(Path(args.resources))
    global_cfg = contract["global"]
    os.environ.setdefault("GCP_PROJECT_ID", "")
    project_id = os.environ.get(global_cfg["project_id_env"], "")
    if not project_id:
        raise SystemExit(f"set {global_cfg['project_id_env']} in the runner environment")
    ssh_key = os.environ.get(global_cfg["ssh_public_key_env"], "")
    if not ssh_key:
        raise SystemExit(f"set {global_cfg['ssh_public_key_env']} in the runner environment")
    ssh_cidrs = [value.strip() for value in os.environ.get(global_cfg["ssh_cidr_env"], "").split(",") if value.strip()]
    source_cidrs = [value.strip() for value in os.environ.get(global_cfg["source_cidr_env"], "").split(",") if value.strip()]
    if not ssh_cidrs or not source_cidrs:
        raise SystemExit("GCP UAT requires non-empty SSH and HTTPS allowlists")
    if any("/32" not in cidr and "/128" not in cidr for cidr in ssh_cidrs + source_cidrs):
        raise SystemExit("GCP UAT allowlists must contain fixed /32 or /128 entries")
    global_cfg["ssh_keys"] = [f"{global_cfg.get('ssh_user', 'ubuntu')}:{ssh_key}"]
    global_cfg["ssh_cidrs"] = ssh_cidrs
    global_cfg["source_cidrs"] = source_cidrs
    hosts = global_cfg["hosts"]
    cpa_ports = [host["cpa_port"] for host in hosts if host["role"] == "cpa"]
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    rendered = renderer(contract).get_template("ai-aggregator-hosts.tf.j2").render(
        **{"global": global_cfg, "hosts": hosts, "cpa_ports": cpa_ports}
    )
    (workdir / "generated_hosts.tf").write_text(rendered, encoding="utf-8")
    (workdir / "terraform.auto.tfvars.json").write_text(
        json.dumps({"project_id": project_id}, indent=2) + "\n", encoding="utf-8"
    )
    (workdir / ".gitignore").write_text(
        ".terraform/\n.terraform.lock.hcl\n*.tfstate*\ngenerated_hosts.tf\n"
        "terraform.auto.tfvars.json\ncmdb.json\ninventory.ini\n",
        encoding="utf-8",
    )
    print(f"rendered {workdir / 'generated_hosts.tf'}")


def inventory(args: argparse.Namespace) -> None:
    contract = load_contract(Path(args.resources))
    workdir = Path(args.workdir)
    output = subprocess.check_output(
        ["terraform", f"-chdir={workdir}", "output", "-json", "cmdb_runtime"],
        text=True,
    )
    runtime = json.loads(output)
    ssh_user = contract["global"].get("ssh_user", "ubuntu")
    lines = ["[ai_aggregator_gateway]"]
    hosts = contract["global"]["hosts"]
    for host in hosts:
        if host["role"] == "gateway":
            item = runtime[host["id"]]
            lines.append(f"{host['id']} ansible_host={item['ip']} ansible_user={ssh_user} cpa_instance_id=")
    lines += ["", "[ai_aggregator_cpa]"]
    for host in hosts:
        if host["role"] == "cpa":
            item = runtime[host["id"]]
            lines.append(
                f"{host['id']} ansible_host={item['ip']} ansible_user={ssh_user} "
                f"cpa_instance_id={host['id']}"
            )
    lines += ["", "[all:vars]", "ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'"]
    (workdir / "inventory.ini").write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmdb = {
        host["id"]: {
            "ip": runtime[host["id"]]["ip"],
            "private_ip": runtime[host["id"]]["private_ip"],
            "instance_id": runtime[host["id"]]["instance_id"],
            "role": host["role"],
            "groups": ["ai_aggregator_gateway" if host["role"] == "gateway" else "ai_aggregator_cpa"],
        }
        for host in hosts
    }
    (workdir / "cmdb.json").write_text(json.dumps(cmdb, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {workdir / 'inventory.ini'} and {workdir / 'cmdb.json'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["render", "inventory"])
    parser.add_argument("--resources", required=True)
    parser.add_argument("--workdir", required=True)
    args = parser.parse_args()
    {"render": render, "inventory": inventory}[args.command](args)


if __name__ == "__main__":
    main()
