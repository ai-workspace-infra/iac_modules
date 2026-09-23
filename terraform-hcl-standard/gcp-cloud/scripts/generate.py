#!/usr/bin/env python3
"""Render GCP GitOps resource declarations into Terraform and CMDB artifacts."""

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


def normalize_resources(document):
    """Normalize the legacy platform manifest and namespace declarations."""
    if "global" in document:
        global_config = dict(document["global"])
        cloud_run_services = list(document.get("cloud_run_services", []))
        legacy_cloud_run = bool(global_config.get("cloud_run_service_name"))
        if legacy_cloud_run:
            cloud_run_services.insert(
                0,
                {
                    "name": global_config["cloud_run_service_name"],
                    "image": global_config.get("cloud_run_image"),
                    "region": global_config.get("region"),
                    "module_name": "cloud_run",
                },
            )
        for service in cloud_run_services:
            service.setdefault("region", global_config.get("region"))
            service.setdefault("module_name", f"cloud_run_{tf_id(service['name'])}")
        return (
            global_config,
            list(document.get("vault_nodes", [])),
            list(document.get("spot_vms", [])),
            cloud_run_services,
            legacy_cloud_run,
        )

    if document.get("kind") != "GCPWorkloadNamespace":
        raise SystemExit("manifest must declare `global` or kind GCPWorkloadNamespace")
    metadata = document.get("metadata", {})
    spec = document.get("spec", {})
    environment = metadata.get("environment")
    if environment not in {"uat", "prod"}:
        raise SystemExit("metadata.environment must be uat or prod")
    if metadata.get("provider") != "gcp":
        raise SystemExit("metadata.provider must be gcp")

    resources = spec.get("resources", {})
    global_config = {
        "environment": environment,
        "bootstrap_project_id": spec.get("bootstrap_project_id", ""),
        "project_id": spec.get("project_id"),
        "project_name": spec.get("project_name", ""),
        "organization_id": spec.get("organization_id"),
        "region": spec.get("region"),
        "network_name": spec.get("network_name"),
        "subnet_cidr": spec.get("subnet_cidr"),
        "enable_cloud_nat": spec.get("enable_cloud_nat", True),
        "artifact_registry_location": spec.get("artifact_registry_location"),
        "artifact_registry_id": spec.get("artifact_registry_id"),
    }
    required_spec = (
        "gcp_account_id",
        "project_id",
        "organization_id",
        "region",
        "workspace",
        "state_namespace",
        "network_name",
        "subnet_cidr",
    )
    missing = [key for key in required_spec if not spec.get(key)]
    if missing:
        raise SystemExit(f"GCPWorkloadNamespace spec is missing: {', '.join(missing)}")
    name = metadata.get("name")
    if spec["workspace"] != name or spec["state_namespace"] != name:
        raise SystemExit("metadata.name, spec.workspace, and spec.state_namespace must match")
    state_key = spec.get("state", {}).get("key")
    expected_state_key = (
        f"terraform/{environment}/{spec['project_id']}/gcp-cloud/"
        f"{spec['gcp_account_id']}/{name}/terraform.tfstate"
    )
    if state_key != expected_state_key:
        raise SystemExit(f"state.key must be {expected_state_key}")
    cloud_run_services = [dict(item) for item in resources.get("cloud_run_services", [])]
    for service in cloud_run_services:
        service.setdefault("region", global_config.get("region"))
        service.setdefault("module_name", f"cloud_run_{tf_id(service['name'])}")
    spot_vms = [dict(item) for item in resources.get("spot_vms", [])]
    if not spot_vms and not cloud_run_services:
        raise SystemExit("GCPWorkloadNamespace must declare at least one Spot VM or Cloud Run service")
    for vm in spot_vms:
        required = ("name", "zone", "machine_type")
        missing = [key for key in required if not vm.get(key)]
        if missing:
            raise SystemExit(f"Spot VM is missing required fields: {', '.join(missing)}")
        if not str(vm["zone"]).startswith(f"{global_config['region']}-"):
            raise SystemExit(f"Spot VM zone {vm['zone']} must belong to region {global_config['region']}")
        duration = int(vm.get("max_run_duration_seconds", 3600))
        if duration < 60:
            raise SystemExit("Spot VM max_run_duration_seconds must be at least 60")
        vm["max_run_duration_seconds"] = duration
    return (
        global_config,
        list(resources.get("vault_nodes", [])),
        spot_vms,
        cloud_run_services,
        False,
    )


def render(args):
    document = load_resources(args.resources)
    global_config, declared_nodes, spot_vms, cloud_run_services, legacy_cloud_run = normalize_resources(document)
    nodes = []
    for node in declared_nodes:
        item = dict(node)
        item.setdefault("machine_type", global_config.get("vault_machine_type"))
        item.setdefault("image", global_config.get("vault_image"))
        nodes.append(item)

    # Optional platform components are rendered only when the manifest
    # declares them, so a minimal manifest (for example a Spot VM validation
    # stack) does not plan the full platform.
    enable_network = bool(global_config.get("network_name"))
    enable_artifact_registry = bool(global_config.get("artifact_registry_id"))
    enable_cloud_run = bool(cloud_run_services)
    if (nodes or spot_vms) and not enable_network:
        raise SystemExit("vault_nodes/spot_vms require a declared network_name and subnet_cidr")
    if enable_network and not global_config.get("subnet_cidr"):
        raise SystemExit("network_name requires subnet_cidr")
    if enable_artifact_registry and not global_config.get("artifact_registry_location"):
        raise SystemExit("global.artifact_registry_id requires global.artifact_registry_location")
    for service in cloud_run_services:
        if not service.get("name") or not service.get("image"):
            raise SystemExit("each cloud_run_services item requires name and image")
    module_names = [service["module_name"] for service in cloud_run_services]
    if len(module_names) != len(set(module_names)):
        raise SystemExit("Cloud Run service names must render to unique Terraform module names")
    project_id = global_config.get("project_id")
    if not project_id:
        raise SystemExit("manifest requires project_id")

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
        spot_vms=spot_vms,
        cloud_run_services=cloud_run_services,
        vault_machine_type=global_config.get("vault_machine_type", ""),
        vault_image=global_config.get("vault_image", ""),
        enable_network=enable_network,
        enable_artifact_registry=enable_artifact_registry,
        enable_cloud_run=enable_cloud_run,
        legacy_cloud_run=legacy_cloud_run,
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
        "enable_cloud_nat",
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
        json.dumps(
            {
                "environment": global_config["environment"],
                "project_id": project_id,
                "vault_nodes": nodes,
                "spot_vms": spot_vms,
                "cloud_run_services": cloud_run_services,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"rendered {args.resources} -> {workdir}")


def inventory(args):
    document = load_resources(args.resources)
    global_config, declared_nodes, spot_vms, cloud_run_services, _ = normalize_resources(document)
    workdir = Path(args.workdir)
    raw = subprocess.check_output(
        ["terraform", f"-chdir={workdir}", "output", "-json", "platform_runtime"],
        text=True,
    )
    runtime = json.loads(raw)
    environment = global_config["environment"]
    cmdb = {
        "environment": environment,
        "project_id": runtime.get("project_id"),
        "project_number": runtime.get("project_number"),
        "cloud_run_uri": runtime.get("cloud_run_uri"),
        "oidc_provider": runtime.get("oidc_provider"),
        "deploy_account": runtime.get("deploy_account"),
        "cloud_run_services": runtime.get("cloud_run_services", {}),
        "spot_instances": runtime.get("spot_instances", {}),
        "vault_nodes": [
            {
                "name": node["name"],
                "zone": node["zone"],
                "private_ip": runtime.get("vault_private_ips", {}).get(node["name"]),
            }
            for node in declared_nodes
        ],
        "declared_cloud_run_services": [item["name"] for item in cloud_run_services],
        "declared_spot_vms": [item["name"] for item in spot_vms],
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
