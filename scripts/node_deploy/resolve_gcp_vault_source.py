#!/usr/bin/env python3
"""Resolve the declared GCP migration source into a provider-neutral contract."""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path

from render_inventory import validate


STAGES = ["xconnect-one", "vault-legacy-convert", "vault-legacy-rollback", "vault-legacy-retire", "vault-single-raft"]
STAGE_TARGETS = {
    "xconnect-one": ["xconnect_one"],
    "vault-legacy-convert": ["vault_legacy_source"],
    "vault-legacy-rollback": ["vault_legacy_source"],
    "vault-legacy-retire": ["vault_legacy_source"],
    "vault-single-raft": ["vault_single_node"],
}


def resolve(config: dict, instances: list[dict], ssh_user: str) -> dict:
    required = ("source_id", "source_zone", "project_id", "network_name", "expected_address", "ssh_host_ed25519")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError(f"source GCP config is missing {', '.join(missing)}")
    indexed = {(item.get("name"), str(item.get("zone", "")).rsplit("/", 1)[-1]): item for item in instances}
    instance = indexed.get((config["source_id"], config["source_zone"]))
    if not instance or instance.get("status") != "RUNNING":
        raise ValueError(f"declared source VM {config['source_id']} is not RUNNING")
    interfaces = instance.get("networkInterfaces", [])
    if len(interfaces) != 1 or not interfaces[0].get("network", "").endswith("/networks/" + config["network_name"]):
        raise ValueError("source VM must have exactly one interface on the declared network")
    private_ip = interfaces[0].get("networkIP")
    if not private_ip or not ipaddress.ip_address(private_ip).is_private:
        raise ValueError("source VM has no private address")
    public_ips = [item.get("natIP") for item in interfaces[0].get("accessConfigs", []) if item.get("natIP")]
    if len(public_ips) != 1 or public_ips[0] != config["expected_address"]:
        raise ValueError("source VM public address differs from the reviewed migration source")
    overlay = config.get("overlay_address")
    if overlay and not ipaddress.ip_address(overlay).is_private:
        raise ValueError("source overlay address must be private")
    source_role = config.get("xconnect_role", "one")
    if source_role not in {"gateway", "one"}:
        raise ValueError("source GCP xconnect_role must be gateway or one")
    xconnect_group = "xconnect_gateway" if source_role == "gateway" else "xconnect_one"
    node = {
        "id": config["source_id"],
        "provider": "gcp",
        "address": public_ips[0],
        # A source retained as Gateway still advertises its original VPC
        # address in Raft. XConnect routes that address during the handoff.
        "private_address": private_ip if source_role == "gateway" else (overlay or private_ip),
        "overlay_address": overlay or None,
        "ssh_host_ed25519": config["ssh_host_ed25519"],
        "ssh_user": ssh_user,
        "auth": {"adapter": "gcp-oslogin-ephemeral"},
        "groups": ["vault_legacy_source", "vault_shared_leader", "vault_single_node", xconnect_group],
    }
    node = {key: value for key, value in node.items() if value is not None}
    stages = STAGES if source_role == "one" else [stage for stage in STAGES if stage != "xconnect-one"]
    stage_targets = {stage: groups for stage, groups in STAGE_TARGETS.items() if stage in stages}
    return validate({
        "apiVersion": "ops.svc.plus/v1alpha1",
        "kind": "NodeDeployment",
        "metadata": {"name": "vault-server"},
        "spec": {
            "environment": config["environment"],
            "stages": stages,
            "stage_targets": stage_targets,
            "connection": {"mode": "bootstrap-public"},
            "nodes": [node],
        },
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--instances", type=Path, required=True)
    parser.add_argument("--ssh-user", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        document = resolve(config, json.loads(args.instances.read_text(encoding="utf-8")), args.ssh_user)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"GCP migration source: {error}") from None
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    args.output.chmod(0o600)
    print(f"resolved GCP migration source {document['spec']['nodes'][0]['id']} into {args.output}")


if __name__ == "__main__":
    main()
