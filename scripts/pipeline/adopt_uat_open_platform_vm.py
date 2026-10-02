#!/usr/bin/env python3
"""Safely import the GitOps-declared UAT Open Platform VM when it already exists."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

import yaml


VM_ADDRESS = "module.open_platform_uat.google_compute_instance.this"


def _run(command: list[str], runner: Callable = subprocess.run) -> subprocess.CompletedProcess:
    return runner(command, check=False, capture_output=True, text=True)


def _require_success(result: subprocess.CompletedProcess, context: str) -> str:
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"{context} failed: {detail}")
    return result.stdout or ""


def _resource_basename(value: str) -> str:
    return value.rstrip("/").split("/")[-1]


def _manifest_spec(path: Path) -> tuple[dict, dict]:
    with path.open(encoding="utf-8") as stream:
        manifest = yaml.safe_load(stream)
    if not isinstance(manifest, dict):
        raise RuntimeError("GitOps resource manifest must contain a YAML mapping")
    global_config = manifest.get("global") or {}
    nodes = manifest.get("vault_nodes") or []
    if global_config.get("environment") != "uat":
        raise RuntimeError("VM state adoption is restricted to a UAT GitOps declaration")
    if global_config.get("project_id") != "open-platform-uat":
        raise RuntimeError("UAT Open Platform VM adoption requires project_id=open-platform-uat")
    if not global_config.get("project_id") or not global_config.get("network_name"):
        raise RuntimeError("GitOps declaration must define global.project_id and global.network_name")
    if len(nodes) != 1:
        raise RuntimeError("Open Platform UAT adoption requires exactly one declared vault_nodes entry")
    node = nodes[0]
    for key in ("name", "zone", "machine_type", "public_ip"):
        if key not in node:
            raise RuntimeError(f"GitOps vault_nodes entry is missing required field: {key}")
    return global_config, node


def _gcloud_json(command: list[str], runner: Callable) -> dict:
    result = _run(command, runner)
    output = _require_success(result, "GCP resource inspection")
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GCP resource inspection returned invalid JSON: {exc}") from exc


def adopt_if_present(manifest_path: Path, terraform_dir: Path, runner: Callable = subprocess.run) -> str:
    global_config, node = _manifest_spec(manifest_path)
    project = global_config["project_id"]
    network = global_config["network_name"]
    name = node["name"]
    zone = node["zone"]
    region = zone.rsplit("-", 1)[0]
    instance_id = f"projects/{project}/zones/{zone}/instances/{name}"

    state_result = _run(["terraform", f"-chdir={terraform_dir}", "state", "list"], runner)
    state = _require_success(state_result, "Terraform state list").splitlines()

    instance_result = _run(
        ["gcloud", "compute", "instances", "describe", name, "--project", project,
         "--zone", zone, "--format=json"],
        runner,
    )
    if instance_result.returncode:
        detail = (instance_result.stderr or instance_result.stdout or "").strip()
        if "was not found" in detail.lower():
            return f"GitOps-declared VM {name} is not present; Terraform will create it."
        raise RuntimeError(f"Could not inspect declared GCP VM {name}: {detail}")
    instance = json.loads(instance_result.stdout or "{}")

    if instance.get("name") != name:
        raise RuntimeError(f"GCP VM name mismatch: expected {name}, got {instance.get('name')!r}")
    if _resource_basename(instance.get("zone", "")) != zone:
        raise RuntimeError(f"GCP VM zone mismatch for {name}")
    if _resource_basename(instance.get("machineType", "")) != node["machine_type"]:
        raise RuntimeError(f"GCP VM machine type differs from GitOps for {name}")
    network_interfaces = instance.get("networkInterfaces") or []
    if not network_interfaces or _resource_basename(network_interfaces[0].get("network", "")) != network:
        raise RuntimeError(f"GCP VM network differs from GitOps for {name}")
    if _resource_basename(network_interfaces[0].get("subnetwork", "")) != f"{network}-subnet":
        raise RuntimeError(f"GCP VM subnet differs from the declared network for {name}")

    nat_ips = [
        config.get("natIP")
        for interface in network_interfaces
        for config in interface.get("accessConfigs", [])
        if config.get("natIP")
    ]
    if bool(node["public_ip"]) != bool(nat_ips):
        raise RuntimeError(f"GCP VM public-IP presence differs from GitOps for {name}")
    if node["public_ip"]:
        address = _gcloud_json(
            ["gcloud", "compute", "addresses", "describe", f"{name}-public-ip",
             "--project", project, "--region", region, "--format=json"],
            runner,
        )
        if address.get("address") not in nat_ips:
            raise RuntimeError(f"GCP VM {name} is not attached to its declared reserved public IP")

    runtime_sa = f"{name}-runtime@{project}.iam.gserviceaccount.com"
    service_accounts = instance.get("serviceAccounts") or []
    if not any(item.get("email") == runtime_sa for item in service_accounts):
        raise RuntimeError(f"GCP VM {name} is not using its GitOps-declared runtime service account")

    if VM_ADDRESS in state:
        return f"Terraform state already manages the verified GCP VM {name}."

    _require_success(
        _run(["terraform", f"-chdir={terraform_dir}", "import", "-input=false", "-no-color",
              VM_ADDRESS, instance_id], runner),
        f"Terraform import of {instance_id}",
    )
    verified_state = _require_success(
        _run(["terraform", f"-chdir={terraform_dir}", "state", "list"], runner),
        "Terraform state verification",
    ).splitlines()
    if VM_ADDRESS not in verified_state:
        raise RuntimeError(f"Terraform import did not record {VM_ADDRESS} in state")
    show = _require_success(
        _run(["terraform", f"-chdir={terraform_dir}", "state", "show", "-no-color", VM_ADDRESS], runner),
        "Terraform imported-resource verification",
    )
    if instance_id not in show:
        raise RuntimeError("Imported Terraform resource ID does not match the verified GCP VM")
    return f"Safely adopted existing GitOps-declared GCP VM {name} into Terraform state."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--terraform-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(adopt_if_present(args.manifest, args.terraform_dir))
    except (OSError, RuntimeError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
