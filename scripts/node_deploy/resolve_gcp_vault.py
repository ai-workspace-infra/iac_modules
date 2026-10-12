#!/usr/bin/env python3
"""Resolve a reviewed GCP Vault GitOps manifest into the common node contract."""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path

import yaml

from render_inventory import validate


STAGES = [
    "node-preflight",
    "node-operator-prep",
    "vault-shared-leader",
    "vault-shared-peers",
    "node-process-metrics",
    "vault-gateway-frontend",
    "vault-public-frontend",
    "xconnect-gateway-identity",
    "xconnect-gateway",
    "xconnect-one",
]
RAFT_PORTS = (8200, 8201)
STAGE_TARGETS = {
    "node-preflight": ["vault_shared_nodes"],
    "node-operator-prep": ["vault_shared_nodes"],
    "vault-shared-leader": ["vault_shared_leader"],
    "vault-shared-peers": ["vault_shared_peers"],
    "node-process-metrics": ["vault_shared_nodes"],
    "vault-gateway-frontend": ["xconnect_gateway"],
    "vault-public-frontend": ["vault_shared_nodes"],
    "xconnect-gateway-identity": ["xconnect_gateway"],
    "xconnect-gateway": ["xconnect_gateway"],
    "xconnect-one": ["xconnect_one"],
}


def allows_port(rule: dict, port: int) -> bool:
    for allowed in rule.get("allowed", []):
        protocol = allowed.get("IPProtocol")
        if protocol == "all":
            return True
        if protocol != "tcp":
            continue
        ports = allowed.get("ports")
        if not ports:
            return True
        for entry in ports:
            low, _, high = str(entry).partition("-")
            if int(low) <= port <= int(high or low):
                return True
    return False


def verify_private_raft_channel(manifest: dict, firewalls: list[dict], target_tag: str = "vault") -> None:
    """Require Raft ports to be reachable from the declared subnet and nowhere public."""
    spec = manifest["spec"]
    network = spec["network_name"]
    subnet = ipaddress.ip_network(spec["subnet_cidr"], strict=True)
    covered: set[int] = set()
    for rule in firewalls:
        if (
            rule.get("disabled") is True
            or rule.get("direction", "INGRESS") != "INGRESS"
            or not str(rule.get("network", "")).endswith(f"/networks/{network}")
            or "allowed" not in rule
        ):
            continue
        tags = rule.get("targetTags")
        if tags and target_tag not in tags:
            continue
        sources = [ipaddress.ip_network(value, strict=False) for value in rule.get("sourceRanges", [])]
        for port in RAFT_PORTS:
            if not allows_port(rule, port):
                continue
            if any(not source.is_private for source in sources):
                raise ValueError(f"firewall rule {rule.get('name')} exposes Vault port {port} publicly")
            if sources and all(source.subnet_of(subnet) for source in sources):
                covered.add(port)
    missing = [str(port) for port in RAFT_PORTS if port not in covered]
    if missing:
        raise ValueError(f"no private Raft firewall rule for port(s) {', '.join(missing)} from {subnet}")


def overlay_address_of(topology: dict | None, name: str) -> str | None:
    """The node's recorded XConnect overlay IP, or None until Zero has assigned one.

    The overlay IPs only exist after xconnect-gateway / xconnect-one enroll the
    nodes, so a missing IP must not block those stages; the Raft stages refuse
    through the raft-overlay check instead.
    """
    if topology is None:
        raise ValueError("Raft over the overlay needs the XConnect topology")
    spec = topology["spec"]
    members = [spec["gateway"], *spec.get("fixed_nodes", [])]
    target = next((member for member in members if member.get("id") == name), None)
    overlay_ip = (target or {}).get("xconnect", {}).get("overlay_ip")
    if overlay_ip in (None, ""):
        return None
    network = ipaddress.ip_network(spec["network"]["cidr"], strict=True)
    try:
        assigned = ipaddress.ip_address(overlay_ip)
    except (TypeError, ValueError):
        raise ValueError(f"{name} overlay IP {overlay_ip!r} is not an IP address") from None
    if assigned not in network or assigned == network.network_address:
        raise ValueError(f"{name} overlay IP is outside the declared overlay")
    return str(assigned)


def resolve(
    manifest: dict,
    service: dict,
    instances: list[dict],
    project_id: str,
    environment: str,
    ssh_user: str,
    topology: dict | None = None,
) -> dict:
    """Resolve declared GCP Vault nodes.

    With ``spec.migration`` declared, every new node is a Raft peer that joins
    the existing vault.svc.plus node (the only member of the leader group) and,
    for ``raft_network: overlay``, advertises its XConnect overlay address so
    the old node can reach it.
    """
    if manifest.get("kind") != "GCPWorkloadNamespace":
        raise ValueError("expected GCPWorkloadNamespace manifest")
    metadata = manifest["metadata"]
    spec = manifest["spec"]
    if (metadata.get("environment"), spec.get("project_id")) != (environment, project_id):
        raise ValueError("GCP environment or project identity does not match GitOps")
    if service.get("kind") != "VaultServerDeployment" or service.get("metadata", {}).get("environment") != environment:
        raise ValueError("Vault service declaration belongs to another environment")
    service_spec = service["spec"]
    storage = service_spec["storage"]
    if storage.get("backend") != "raft" or storage.get("address_scope") != "private":
        raise ValueError("Vault service must use private Raft storage")
    declared_stages = service_spec.get("stages")
    if not isinstance(declared_stages, list) or not set(declared_stages) <= set(STAGES):
        raise ValueError("Vault service stages are not all supported by the reviewed runner")
    migration = service_spec.get("migration")
    raft_network = (migration or {}).get("raft_network", "private")
    if raft_network not in {"private", "overlay"}:
        raise ValueError("spec.migration.raft_network must be private or overlay")
    if spec.get("enable_oslogin") is not True or spec.get("enable_iap_ssh") is not False:
        raise ValueError("shared Vault deployment requires OS Login and direct allowlisted SSH")
    access_mode = spec.get("ssh_access_mode", "bootstrap-public")
    if access_mode not in {
        service_spec["access"]["bootstrap"],
        service_spec["access"]["steady_state"],
    }:
        raise ValueError("GCP SSH access mode is not declared by the Vault service")
    if access_mode == "bootstrap-public":
        if not spec.get("ssh_source_ranges"):
            raise ValueError("bootstrap-public requires an explicit public SSH /32 allowlist")
    elif access_mode == "xconnect-zero":
        if spec.get("ssh_source_ranges") or topology is None:
            raise ValueError("xconnect-zero requires no public SSH allowlist and a verified topology")
        if topology.get("kind") != "XConnectOneNodeSet" or topology.get("metadata", {}).get("environment") != environment:
            raise ValueError("XConnect topology belongs to another environment")
        overlay_network = ipaddress.ip_network(topology["spec"]["network"]["cidr"], strict=True)
        network_id = topology["spec"]["network"]["id"]
        if network_id != topology["spec"].get("control_plane", {}).get("network_id"):
            raise ValueError("XConnect topology and control plane network identities differ")
    else:
        raise ValueError("unsupported SSH access mode")
    declared = spec["resources"]["vault_nodes"]
    service_nodes = service_spec["nodes"]
    service_roles = {node["id"]: node["xconnect_role"] for node in service_nodes}
    declared_roles = {node["name"]: node["xconnect_role"] for node in declared}
    node_count = len(declared)
    if node_count not in {1, 3}:
        raise ValueError("GCP Vault scale must be one or three nodes")
    migration_source = (migration or {}).get("source", {}).get("id")
    transitional_single_peer = bool(migration and node_count == 1 and service_roles.get(next(iter(service_roles), "")) == "one")
    if transitional_single_peer:
        expected_roles = ["one"]
        storage_shape_ok = (
            storage.get("members") == node_count
            and (
                (storage.get("leader") == migration_source and set(storage.get("peers", [])) == set(service_roles))
                or (storage.get("leader") in service_roles and not storage.get("peers", []))
            )
        )
    else:
        expected_roles = ["gateway"] if node_count == 1 else ["gateway", "one", "one"]
        storage_shape_ok = (
            storage.get("members") == node_count
            and storage.get("leader") in service_roles
            and service_roles[storage["leader"]] == "gateway"
            and set(storage.get("peers", [])) == set(service_roles) - {storage["leader"]}
        )
    if (
        len(service_roles) != node_count
        or declared_roles != service_roles
        or sorted(service_roles.values()) != sorted(expected_roles)
        or not storage_shape_ok
    ):
        raise ValueError("GCP nodes do not match the provider-neutral Vault service declaration")
    live = {(item.get("name"), item.get("zone", "").split("/")[-1]): item for item in instances}
    nodes = []
    for node in declared:
        name = node["name"]
        zone = node["zone"]
        actual = live.get((name, zone))
        if not actual or actual.get("status") != "RUNNING":
            raise ValueError(f"declared VM {name} ({zone}) is not RUNNING")
        interfaces = actual.get("networkInterfaces", [])
        if len(interfaces) != 1:
            raise ValueError(f"declared VM {name} must have exactly one network interface")
        private_ip = interfaces[0].get("networkIP")
        public_ips = [config.get("natIP") for config in interfaces[0].get("accessConfigs", [])]
        public_ips = [value for value in public_ips if value]
        if node.get("public_ip") is not True or len(public_ips) != 1:
            raise ValueError(f"declared VM {name} is missing its required public SSH address")
        role = node["xconnect_role"]
        if not node.get("ssh_host_ed25519"):
            raise ValueError(f"declared VM {name} has no reviewed SSH host key")
        groups = ["vault_shared_nodes", "xconnect_gateway" if role == "gateway" else "xconnect_one"]
        if migration:
            # The existing node leads; every new node joins it as a peer.
            groups.append("vault_shared_peers")
        else:
            groups.append("vault_shared_leader" if role == "gateway" else "vault_shared_peers")
        resolved = {
                "id": name,
                "provider": "gcp",
                "address": public_ips[0],
                "private_address": private_ip,
                "ssh_host_ed25519": node.get("ssh_host_ed25519"),
                "ssh_user": ssh_user,
                "auth": {"adapter": "gcp-oslogin-ephemeral"},
                "groups": groups,
            }
        if access_mode == "xconnect-zero":
            members = [topology["spec"]["gateway"], *topology["spec"]["fixed_nodes"]]
            target = next((member for member in members if member.get("id") == name), None)
            if target is None:
                raise ValueError(f"XConnect topology is missing {name}")
            overlay = target.get("xconnect", {})
            overlay_ip = overlay.get("overlay_ip")
            internal_dns = overlay.get("internal_dns")
            try:
                assigned = ipaddress.ip_address(overlay_ip)
            except (TypeError, ValueError):
                raise ValueError(f"XConnect node {name} has no assigned overlay IP") from None
            if assigned not in overlay_network or assigned == overlay_network.network_address:
                raise ValueError(f"XConnect node {name} is outside the declared overlay")
            if not isinstance(internal_dns, str) or "." not in internal_dns:
                raise ValueError(f"XConnect node {name} has no internal DNS name")
            resolved["address"] = internal_dns
            resolved["overlay_address"] = overlay_ip
        if raft_network == "overlay":
            # Until the overlay IP is recorded the node keeps its VPC address;
            # migrate-join refuses (raft-overlay) so Raft never uses it.
            overlay_ip = overlay_address_of(topology, name)
            if overlay_ip:
                resolved["overlay_address"] = overlay_ip
                resolved["private_address"] = overlay_ip
        nodes.append(resolved)
    # A migration never initializes a new leader: the existing node leads.
    stages = [stage for stage in STAGES if not (migration and stage == "vault-shared-leader")]
    declared_groups = {group for node in nodes for group in node["groups"]}
    stage_targets = {
        stage: STAGE_TARGETS[stage]
        for stage in stages
        if all(group in declared_groups for group in STAGE_TARGETS[stage])
    }
    contract = {
        "apiVersion": "ops.svc.plus/v1alpha1",
        "kind": "NodeDeployment",
        "metadata": {"name": metadata["name"]},
        "spec": {
            "environment": environment,
            "stages": list(stage_targets),
            "stage_targets": stage_targets,
            "connection": {"mode": access_mode},
            "nodes": nodes,
        },
    }
    return validate(contract)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--service-manifest", type=Path, required=True)
    parser.add_argument("--instances", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--ssh-user", required=True)
    parser.add_argument("--xconnect-topology", type=Path)
    parser.add_argument("--firewalls", type=Path, required=True, help="gcloud compute firewall-rules list JSON")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    service = yaml.safe_load(args.service_manifest.read_text(encoding="utf-8"))
    expected_topology = Path("gitops") / service["spec"]["access"]["xconnect_topology"]
    if args.xconnect_topology != expected_topology:
        raise SystemExit("XConnect topology path differs from the reviewed Vault service declaration")
    instances = json.loads(args.instances.read_text(encoding="utf-8"))
    topology = yaml.safe_load(args.xconnect_topology.read_text(encoding="utf-8")) if args.xconnect_topology else None
    contract = resolve(manifest, service, instances, args.project_id, args.environment, args.ssh_user, topology)
    try:
        verify_private_raft_channel(manifest, json.loads(args.firewalls.read_text(encoding="utf-8")))
    except ValueError as error:
        raise SystemExit(f"private Raft channel check failed: {error}") from None
    args.output.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    args.output.chmod(0o600)
    print(f"resolved {len(contract['spec']['nodes'])} GCP Vault nodes into {args.output}")


if __name__ == "__main__":
    main()
