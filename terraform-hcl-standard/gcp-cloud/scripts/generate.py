#!/usr/bin/env python3
"""Render GCP platform YAML into explicit Terraform and CMDB artifacts."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
GITOPS_ROOT = Path(os.environ.get("GITOPS_ROOT", ROOT.parents[2] / "gitops"))
DEFAULT_RESOURCES = GITOPS_ROOT / "resources" / "xworktech.com" / "uat" / "gcp" / "open-platform-uat.yaml"
DEFAULT_WORKDIR = ROOT / "envs" / "uat"


def tf_id(value):
    return re.sub(r"[^0-9A-Za-z_]", "_", str(value))


def load_resources(path):
    with Path(path).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def render(args):
    resources = load_resources(args.resources)
    global_config = resources.get("global", {})
    nodes = []
    for node in resources.get("vault_nodes", []):
        item = dict(node)
        item.setdefault("machine_type", global_config["vault_machine_type"])
        item.setdefault("image", global_config["vault_image"])
        nodes.append(item)

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    # Remove the legacy generated provider filename so old renders cannot
    # coexist with the platform provider and create duplicate configurations.
    stale_provider = workdir / "provider.tf"
    if stale_provider.exists():
        stale_provider.unlink()
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["tf_id"] = tf_id
    content = env.get_template("open-platform.tf.j2").render(
        environment=global_config["environment"],
        vault_nodes=nodes,
        vault_machine_type=global_config["vault_machine_type"],
        vault_image=global_config["vault_image"],
    )
    generated = workdir / "generated_platform.tf"
    generated.write_text(content, encoding="utf-8")
    subprocess.run(["terraform", "fmt", str(generated)], check=True, stdout=subprocess.DEVNULL)
    (workdir / "backend.tf").write_text(
        (TEMPLATES / "backend.tf").read_text(encoding="utf-8"), encoding="utf-8"
    )
    for name in ("platform-provider.tf", "variables.tf"):
        (workdir / name).write_text((TEMPLATES / name).read_text(encoding="utf-8"), encoding="utf-8")

    # Billing is intentionally absent from YAML and generated tfvars.
    declared = {
        "bootstrap_project_id",
        "project_id",
        "project_name",
        "organization_id",
        "region",
        "github_owner",
        "github_repository",
        "network_name",
        "subnet_cidr",
        "artifact_registry_location",
        "artifact_registry_id",
        "cloud_run_service_name",
        "cloud_run_image",
    }
    tfvars = {key: value for key, value in global_config.items() if key in declared}
    (workdir / "terraform.auto.tfvars.json").write_text(
        json.dumps(tfvars, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (workdir / "resources_manifest.json").write_text(
        json.dumps({"environment": global_config["environment"], "vault_nodes": nodes}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"rendered {args.resources} -> {workdir}")


def inventory(args):
    resources = load_resources(args.resources)
    workdir = Path(args.workdir)
    raw = subprocess.check_output(
        ["terraform", f"-chdir={workdir}", "output", "-json", "platform_runtime"],
        text=True,
    )
    runtime = json.loads(raw)
    environment = resources["global"]["environment"]
    cmdb = {
        "environment": environment,
        "project_id": runtime.get("project_id"),
        "project_number": runtime.get("project_number"),
        "cloud_run_uri": runtime.get("cloud_run_uri"),
        "oidc_provider": runtime.get("oidc_provider"),
        "deploy_account": runtime.get("deploy_account"),
        "vault_nodes": [
            {
                "name": node["name"],
                "zone": node["zone"],
                "private_ip": runtime.get("vault_private_ips", {}).get(node["name"]),
            }
            for node in resources.get("vault_nodes", [])
        ],
    }
    (workdir / "cmdb.json").write_text(json.dumps(cmdb, indent=2) + "\n", encoding="utf-8")
    lines = ["[vault]"]
    lines.extend(f"{node['name']} ansible_host={node['name']}" for node in cmdb["vault_nodes"])
    (workdir / "inventory.ini").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {workdir / 'cmdb.json'} and {workdir / 'inventory.ini'}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("render", "inventory"))
    parser.add_argument("--resources", type=Path, default=DEFAULT_RESOURCES)
    parser.add_argument("--workdir", type=Path, default=DEFAULT_WORKDIR)
    args = parser.parse_args()
    if args.command == "render":
        render(args)
    else:
        inventory(args)


if __name__ == "__main__":
    main()
