#!/usr/bin/env python3
"""Render a GitOps UCloud UHost declaration into an explicit Terraform root."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def tf_id(value: str) -> str:
    result = re.sub(r"[^0-9A-Za-z_]", "_", str(value))
    if not result or result[0].isdigit():
        result = f"host_{result}"
    return result


def hcl(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if data.get("management_mode", "terraform") != "terraform":
        raise SystemExit("UCloud declarations must use management_mode: terraform")
    hosts = data.get("hosts") or []
    if not hosts:
        raise SystemExit("UCloud declaration must contain at least one host")
    names = [str(host.get("name", "")) for host in hosts]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise SystemExit("UCloud host names must be non-empty and unique")
    bootstrap = data.get("bootstrap") or {}
    if not bootstrap.get("security_group_id_env") or not bootstrap.get("key_pair_id_env"):
        raise SystemExit(
            "UCloud declarations must name bootstrap output env vars with "
            "bootstrap.security_group_id_env and bootstrap.key_pair_id_env"
        )
    for key in ("security_group_id_env", "key_pair_id_env"):
        env_name = str(bootstrap[key])
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", env_name):
            raise SystemExit(f"bootstrap.{key} must be an uppercase environment variable name")
    for host in hosts:
        for key in ("security_group_id", "key_pair_id"):
            if host.get(key):
                raise SystemExit(f"UCloud host {host['name']} must receive {key} from the bootstrap Job")
    return data


def render(args) -> None:
    source = Path(args.resources).resolve()
    data = load(source)
    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    for name in ("provider.tf", "variables.tf", "versions.tf"):
        shutil.copyfile(ROOT / name, workdir / name)
    (workdir / "backend.tf").write_text(
        'terraform {\n  backend "s3" {\n    use_lockfile = true\n  }\n}\n',
        encoding="utf-8",
    )

    global_cfg = data.get("global", {}) or {}
    bootstrap = data["bootstrap"]
    network = data.get("network", global_cfg.get("network"))
    lines = ["# Generated from GitOps; do not edit.", ""]
    if network:
        lines += [
            'module "network" {',
            '  source = "../../../modules/network"',
            f"  name = {hcl(network.get('name', 'ucloud-network'))}",
            f"  tag = {hcl(network.get('tag', global_cfg.get('tag', 'Default')))}",
            f"  cidr_blocks = {hcl(network.get('cidr_blocks', ['10.20.0.0/16']))}",
            f"  subnet_cidr_block = {hcl(network.get('subnet_cidr_block', '10.20.1.0/24'))}",
            "}",
            "",
        ]

    outputs = []
    for host in data["hosts"]:
        name = str(host["name"])
        ident = tf_id(name)
        zone = host.get("availability_zone", global_cfg.get("availability_zone"))
        if not zone:
            raise SystemExit(f"UCloud host {name} requires availability_zone")
        image_id = host.get("image_id")
        image_ref = f"data.ucloud_images.{ident}.images[0].id"
        if not image_id:
            regex = host.get("image_name_regex", global_cfg.get("image_name_regex", "^Ubuntu 22.04"))
            lines += [
                f'data "ucloud_images" "{ident}" {{',
                f"  availability_zone = {hcl(zone)}",
                f"  name_regex = {hcl(regex)}",
                '  image_type = "base"',
                "}",
                "",
            ]
        vpc = host.get("vpc_id")
        subnet = host.get("subnet_id")
        if network:
            vpc = "module.network.vpc_id"
            subnet = "module.network.subnet_id"
        lines += [
            f'module "compute_{ident}" {{',
            '  source = "../../../modules/compute"',
            f"  name = {hcl(name)}",
            f"  availability_zone = {hcl(zone)}",
            f"  image_id = {hcl(image_id) if image_id else image_ref}",
            f"  instance_type = {hcl(host.get('instance_type', global_cfg.get('instance_type', 'n-basic-2')))}",
            f"  boot_disk_type = {hcl(host.get('boot_disk_type', 'cloud_ssd'))}",
            "  security_group_id = var.ucloud_bootstrap_security_group_id",
            "  key_pair_id = var.ucloud_bootstrap_key_pair_id",
            f"  login_mode = {hcl(host.get('login_mode', 'KeyPair'))}",
            f"  tag = {hcl(host.get('tag', global_cfg.get('tag', 'Default')))}",
            f"  deletion_protection = {str(bool(host.get('deletion_protection', False))).lower()}",
        ]
        if vpc:
            lines.append(f"  vpc_id = {hcl(vpc) if not str(vpc).startswith('module.') else vpc}")
        if subnet:
            lines.append(f"  subnet_id = {hcl(subnet) if not str(subnet).startswith('module.') else subnet}")
        if host.get("user_data"):
            lines.append(f"  user_data = {hcl(host['user_data'])}")
        lines += ["}", ""]
        outputs.append((name, ident, host))

    lines += [
        'output "cmdb_runtime" {',
        "  value = {",
    ]
    for name, ident, _ in outputs:
        lines += [
            f"    {hcl(name)} = {{",
            f"      instance_id = module.compute_{ident}.instance_id",
            f"      ip_set = module.compute_{ident}.ip_set",
            f"      status = module.compute_{ident}.status",
            "    },",
        ]
    lines += ["  }", "}", ""]
    (workdir / "main.tf").write_text("\n".join(lines), encoding="utf-8")
    (workdir / "ucloud_manifest.json").write_text(
        json.dumps(
            {
                "provider": "ucloud",
                "source": str(source),
                "hosts": [h["name"] for h in data["hosts"]],
                "bootstrap": {
                    "security_group_id_env": bootstrap["security_group_id_env"],
                    "key_pair_id_env": bootstrap["key_pair_id_env"],
                },
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"rendered {source} -> {workdir}")


def inventory(args) -> None:
    workdir = Path(args.workdir).resolve()
    output = subprocess.check_output(
        ["terraform", f"-chdir={workdir}", "output", "-json", "cmdb_runtime"],
        text=True,
    )
    runtime = json.loads(output)
    source = Path(args.resources).resolve()
    data = load(source)
    cmdb = {}
    for host in data["hosts"]:
        name = str(host["name"])
        facts = runtime.get(name, {})
        domains = (host.get("host_vars", {}) or {}).get("service_domains", []) or []
        fqdn = domains[0] if domains else name
        ip_set = facts.get("ip_set") or []
        cmdb[fqdn] = {
            "name": name,
            "fqdn": fqdn,
            "ip": ip_set[0] if ip_set else None,
            "instance_id": facts.get("instance_id"),
            "region": host.get("region", data.get("global", {}).get("region")),
            "type": host.get("instance_type", data.get("global", {}).get("instance_type")),
            "cloud_provider": "ucloud",
            "groups": host.get("groups", []),
            "host_vars": host.get("host_vars", {}),
        }
    (workdir / "cmdb.json").write_text(json.dumps(cmdb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {workdir / 'cmdb.json'}")


parser = argparse.ArgumentParser()
sub = parser.add_subparsers(dest="command", required=True)
for name, handler in (("render", render), ("inventory", inventory)):
    command = sub.add_parser(name)
    command.add_argument("--resources", required=True)
    command.add_argument("--workdir", required=True)
    command.set_defaults(handler=handler)
args = parser.parse_args()
args.handler(args)
