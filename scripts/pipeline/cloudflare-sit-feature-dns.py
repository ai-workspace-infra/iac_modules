#!/usr/bin/env python3
"""Reconcile one owned Dev feature-lane DNS A record; never mutates onwalk.net aliases."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import sys
from urllib.parse import urlencode

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

    def records(self, zone_id: str, name: str) -> list[dict]:
        records = super().records(zone_id, name)
        if any(f"feature-id:{self.feature_id}" not in (r.get("tags") or []) for r in records):
            raise base.OperationError("DNS name is occupied by a record not owned by this Feature ID")
        return records

    def create(self, zone_id: str, payload: dict) -> dict:
        return super().create(zone_id, dict(payload, comment=f"Codex SIT lane {self.feature_id}", tags=[f"feature-id:{self.feature_id}", "owner:iac-modules"]))

    def delete(self, zone_id: str, record_id: str) -> None:
        raise base.OperationError("DNS deletion requires an authenticated lane cleanup receipt; reconcile never deletes")


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
        env = dict(os.environ, DNS_ENVIRONMENT="sit", DNS_ZONE=zone, DNS_RECORD_NAME=name, DNS_TARGET_IP=target)
        config = base.Config.from_env(env)
        client = FeatureCloudflare(base.required(env, "CLOUDFLARE_DNS_API_TOKEN"), base.required(env, "CLOUDFLARE_ACCOUNT_ID"), feature_id)
        result = base.execute(config, client)
        print(json.dumps({"result": "verified", "feature_id": feature_id, "service": service, "hostname": name, **result}, sort_keys=True))
        return 0
    except (base.OperationError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
