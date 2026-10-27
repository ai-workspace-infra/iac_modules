#!/usr/bin/env python3
"""Reconcile one owned Dev feature-lane DNS A record; never mutates onwalk.net aliases."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import sys

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("feature_dns_base", Path(__file__).with_name("cloudflare-gateway-dns-upsert.py"))
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)


def lane_domain(feature_id: str, service: str, zone: str) -> str:
    if not re.fullmatch(r"feature-[a-z][a-z0-9-]{1,48}", feature_id) or feature_id.endswith("-"):
        raise base.OperationError("FEATURE_ID must be a stable lowercase DNS-safe identifier")
    if service not in ("console", "accounts", "billing"):
        raise base.OperationError("unsupported SIT feature service")
    slug = feature_id.removeprefix("feature-")
    normalized_zone = base.domain(zone)
    if normalized_zone != "onwalk.net":
        raise base.OperationError("SIT feature DNS is restricted to the declared onwalk.net zone")
    label = f"{slug}-sit" if service == "console" else f"{service}-{slug}-sit"
    name = f"{label}.{normalized_zone}"
    return base.domain(name)


def dev_ingress_ip(cmdb: dict, node: str) -> str:
    if node != "dev-k3s-v5":
        raise base.OperationError("SIT feature DNS is restricted to the declared Dev ingress node")
    host = cmdb.get(node)
    groups = set(host.get("groups", [])) if isinstance(host, dict) else set()
    if not isinstance(host, dict) or not {"dev", "k3s", "k3s_server", "akamai_cloud"} <= groups:
        raise base.OperationError("CMDB does not identify the declared Dev K3s ingress node")
    try:
        target = ipaddress.IPv4Address(host.get("ip", ""))
    except ipaddress.AddressValueError:
        raise base.OperationError("Dev ingress target must be a valid public IPv4 address") from None
    if not target.is_global:
        raise base.OperationError("Dev ingress target must be a public IPv4 address")
    return str(target)


class FeatureCloudflare(base.Cloudflare):
    def __init__(self, token: str, account_id: str, feature_id: str):
        super().__init__(token, account_id)
        self.feature_id = feature_id

def reconcile_record(client: FeatureCloudflare, zone_id: str, name: str,
                     feature_id: str, target: str, waiter=base.wait_for_dns) -> dict:
    """Reconcile one record and roll back only if our exact write is still current."""
    records = client.records(zone_id, name)
    if len(records) > 1:
        raise base.OperationError("multiple DNS records exist for the feature hostname")
    feature_tag, owner_tag = f"feature-id:{feature_id}", "owner:iac-modules"
    record_id = None
    if not records:
        original = None
        desired = {"type": "A", "name": name, "content": target, "ttl": 60,
                   "proxied": False, "comment": f"SIT feature lane {feature_id}",
                   "tags": [feature_tag, owner_tag]}
        action = "create"
    else:
        current = records[0]
        original = base.record_payload(current)
        record_id = current["id"]
        if current.get("type") != "A":
            raise base.OperationError("feature hostname is occupied by a non-A record")
        tags = set(current.get("tags") or [])
        owners = {tag for tag in tags if tag.startswith("feature-id:")}
        if feature_tag in owners and owner_tag in tags:
            if owners != {feature_tag}:
                raise base.OperationError("DNS record has conflicting Feature ID owners")
            desired = dict(original, content=target, ttl=60, proxied=False,
                           comment=f"SIT feature lane {feature_id}",
                           tags=sorted((tags - owners) | {feature_tag, owner_tag}))
            action = "noop" if original == desired else "update"
        elif not owners and owner_tag not in tags:
            if current.get("content") != target or current.get("proxied") is not False:
                raise base.OperationError("unowned DNS record differs from current Dev target; refusing adoption")
            desired = dict(original, comment=f"SIT feature lane {feature_id}",
                           tags=sorted(tags | {feature_tag, owner_tag}))
            action = "adopt"
        else:
            raise base.OperationError("DNS record is owned by a different lane or owner")

    if action == "create":
        record_id = client.create(zone_id, desired)["id"]
    elif action in ("update", "adopt"):
        client.update(zone_id, record_id, desired)
    if not waiter(name, target):
        try:
            latest = client.records(zone_id, name)
            current = next((row for row in latest if row.get("id") == record_id), None)
            if action == "create":
                if current is not None:
                    if base.record_payload(current) != desired:
                        raise base.OperationError("created DNS record changed before recovery")
                    client.delete(zone_id, record_id)
            elif action in ("update", "adopt"):
                if current is None or base.record_payload(current) != desired:
                    raise base.OperationError("DNS record changed before recovery")
                client.update(zone_id, record_id, original)
        except base.OperationError as error:
            raise base.OperationError(f"resolver convergence failed; recovery failed: {error}") from None
        raise base.OperationError("resolver convergence failed; previous DNS state restored")
    return {"changed": action != "noop", "action": action, "record_id": record_id,
            "address": target}


def main() -> int:
    try:
        feature_id = os.environ.get("FEATURE_ID", "").strip()
        service = os.environ.get("FEATURE_DNS_SERVICE", "").strip()
        zone = base.domain(base.required(os.environ, "DNS_ZONE"))
        if os.environ.get("DNS_ENVIRONMENT") != "sit":
            raise base.OperationError("feature DNS is SIT-only")
        name = lane_domain(feature_id, service, zone)
        cmdb = json.loads(Path(base.required(os.environ, "CMDB_FILE")).read_text())
        node = base.required(os.environ, "DEV_INGRESS_NODE")
        target = dev_ingress_ip(cmdb, node)
        client = FeatureCloudflare(base.required(os.environ, "CLOUDFLARE_DNS_API_TOKEN"),
                                  base.required(os.environ, "CLOUDFLARE_ACCOUNT_ID"), feature_id)
        result = reconcile_record(client, client.zone_id(zone), name, feature_id, target)
        print(json.dumps({"result": "verified", "feature_id": feature_id, "service": service, "hostname": name, **result}, sort_keys=True))
        return 0
    except (base.OperationError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
