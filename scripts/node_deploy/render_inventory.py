#!/usr/bin/env python3
"""Validate a provider-neutral node deployment contract and render Ansible INI."""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import re
from pathlib import Path
from typing import Any


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
HOSTNAME = re.compile(r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*$")
ALLOWED_AUTH_ADAPTERS = {"gcp-oslogin-ephemeral", "ssh-certificate", "ephemeral-ssh-key"}
ALLOWED_STAGES = {
    "node-preflight",
    "node-operator-prep",
    "vault-single-raft",
    "vault-legacy-convert",
    "vault-legacy-rollback",
    "vault-legacy-retire",
    "vault-shared-leader",
    "vault-shared-peers",
    "node-process-metrics",
    "vault-gateway-frontend",
    "vault-public-frontend",
    "xconnect-gateway-identity",
    "xconnect-gateway",
    "xconnect-one",
}


def fail(message: str) -> None:
    raise SystemExit(f"node deployment contract: {message}")


def validate(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or document.get("apiVersion") != "ops.svc.plus/v1alpha1":
        fail("apiVersion must be ops.svc.plus/v1alpha1")
    if document.get("kind") != "NodeDeployment":
        fail("kind must be NodeDeployment")
    metadata = document.get("metadata")
    spec = document.get("spec")
    if not isinstance(metadata, dict) or not IDENTIFIER.fullmatch(str(metadata.get("name", ""))):
        fail("metadata.name is required and must be a safe identifier")
    if not isinstance(spec, dict):
        fail("spec must be an object")
    if set(spec) - {"environment", "stages", "stage_targets", "connection", "nodes"}:
        fail("spec accepts only environment, stages, stage_targets, connection, and nodes")
    connection = spec.get("connection", {"mode": "bootstrap-public"})
    if (
        not isinstance(connection, dict)
        or set(connection) != {"mode"}
        or connection["mode"] not in {"bootstrap-public", "xconnect-zero"}
    ):
        fail("spec.connection.mode must be bootstrap-public or xconnect-zero")
    environment = spec.get("environment")
    if not isinstance(environment, str) or not IDENTIFIER.fullmatch(environment):
        fail("spec.environment is required")
    stages = spec.get("stages")
    if not isinstance(stages, list) or not stages or any(
        not isinstance(stage, str) or stage not in ALLOWED_STAGES for stage in stages
    ):
        fail(f"spec.stages must be a non-empty list from {sorted(ALLOWED_STAGES)}")
    if len(set(stages)) != len(stages):
        fail("spec.stages cannot contain duplicates")
    nodes = spec.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        fail("spec.nodes must be a non-empty list")

    seen: set[str] = set()
    declared_groups: set[str] = set()
    for index, node in enumerate(nodes):
        label = f"spec.nodes[{index}]"
        if not isinstance(node, dict):
            fail(f"{label} must be an object")
        if set(node) - {"id", "provider", "address", "private_address", "overlay_address", "ssh_host_ed25519", "ssh_port", "ssh_user", "auth", "groups"}:
            fail(f"{label} contains unsupported fields; keep credentials outside the node contract")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not IDENTIFIER.fullmatch(node_id) or node_id in seen:
            fail(f"{label}.id must be unique and a safe identifier")
        seen.add(node_id)
        address = node.get("address")
        if not isinstance(address, str) or not address or any(c.isspace() for c in address):
            fail(f"{label}.address must be a hostname or IP address")
        try:
            ipaddress.ip_address(address)
        except ValueError:
            if not HOSTNAME.fullmatch(address):
                fail(f"{label}.address is not a valid hostname or IP address")
        private_address = node.get("private_address")
        if private_address is not None:
            if not isinstance(private_address, str):
                fail(f"{label}.private_address must be a private IP address")
            try:
                private_ip = ipaddress.ip_address(private_address)
            except ValueError:
                fail(f"{label}.private_address must be a private IP address")
            if not private_ip.is_private:
                fail(f"{label}.private_address must be a private IP address")
        overlay_address = node.get("overlay_address")
        if overlay_address is not None:
            try:
                overlay_ip = ipaddress.ip_address(overlay_address)
            except (TypeError, ValueError):
                fail(f"{label}.overlay_address must be a private IP address")
            if not overlay_ip.is_private:
                fail(f"{label}.overlay_address must be a private IP address")
        host_key = node.get("ssh_host_ed25519")
        if host_key is not None:
            if not isinstance(host_key, str) or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", host_key):
                fail(f"{label}.ssh_host_ed25519 must be a base64 public key")
            try:
                decoded = base64.b64decode(host_key, validate=True)
            except ValueError:
                fail(f"{label}.ssh_host_ed25519 must be a base64 public key")
            if not decoded.startswith(b"\x00\x00\x00\x0bssh-ed25519"):
                fail(f"{label}.ssh_host_ed25519 must contain an Ed25519 host public key")
        port = node.get("ssh_port", 22)
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            fail(f"{label}.ssh_port must be between 1 and 65535")
        user = node.get("ssh_user")
        if not isinstance(user, str) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}\$?", user):
            fail(f"{label}.ssh_user must be a POSIX account name")
        provider = node.get("provider", "unspecified")
        if not isinstance(provider, str) or not IDENTIFIER.fullmatch(provider):
            fail(f"{label}.provider must be a safe identifier")
        auth = node.get("auth")
        if (
            not isinstance(auth, dict)
            or not isinstance(auth.get("adapter"), str)
            or auth.get("adapter") not in ALLOWED_AUTH_ADAPTERS
        ):
            fail(f"{label}.auth.adapter must be one of {sorted(ALLOWED_AUTH_ADAPTERS)}")
        if set(auth) - {"adapter", "principal"}:
            fail(f"{label}.auth accepts only adapter and optional principal; never embed credentials")
        principal = auth.get("principal")
        if principal is not None and (
            not isinstance(principal, str) or not principal or any(c.isspace() for c in principal)
        ):
            fail(f"{label}.auth.principal must be a non-empty identifier without whitespace")
        groups = node.get("groups", ["vault_shared_nodes"])
        if not isinstance(groups, list) or not groups or any(
            not isinstance(group, str) or not IDENTIFIER.fullmatch(group) for group in groups
        ):
            fail(f"{label}.groups must be a non-empty list of safe Ansible group names")
        if len(set(groups)) != len(groups):
            fail(f"{label}.groups cannot contain duplicates")
        declared_groups.update(groups)
    stage_targets = spec.get("stage_targets")
    if not isinstance(stage_targets, dict) or set(stage_targets) != set(stages):
        fail("spec.stage_targets must map every declared stage to its target Ansible groups")
    for stage, target_groups in stage_targets.items():
        if (
            not isinstance(target_groups, list)
            or not target_groups
            or any(group not in declared_groups for group in target_groups)
        ):
            fail(f"spec.stage_targets.{stage} must reference declared Ansible groups")
    return document


def render(document: dict[str, Any]) -> str:
    spec = document["spec"]
    lines = ["# Generated from a provider-neutral NodeDeployment contract; do not edit."]
    groups: dict[str, list[dict[str, Any]]] = {}
    for node in spec["nodes"]:
        for group in node.get("groups", ["vault_shared_nodes"]):
            groups.setdefault(group, []).append(node)
    for group, nodes in groups.items():
        lines.append(f"\n[{group}]")
        for node in nodes:
            user = node["ssh_user"]
            port = node.get("ssh_port", 22)
            lines.append(
                f"{node['id']} ansible_host={node['address']} ansible_user={user} "
                f"ansible_port={port} node_provider={node.get('provider', 'unspecified')} "
                f"node_auth_adapter={node['auth']['adapter']} "
                f"vault_shared_private_ip={node.get('private_address', 'unset')}"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args()
    document = validate(json.loads(args.contract.read_text(encoding="utf-8")))
    args.inventory.parent.mkdir(parents=True, exist_ok=True)
    args.inventory.write_text(render(document), encoding="utf-8")
    print(f"validated {document['metadata']['name']}; wrote Ansible inventory to {args.inventory}")


if __name__ == "__main__":
    main()
