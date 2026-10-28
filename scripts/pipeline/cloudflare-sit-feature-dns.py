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


def tagged_lane_domain(feature_id: str, feature_tag: str, service: str, zone: str) -> str:
    """Derive a v2 hostname; provenance must be verified by the caller first."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,45}", feature_id) or feature_id.endswith('-'):
        raise base.OperationError("invalid Feature ID")
    suffix = '-' + feature_id
    if not isinstance(feature_tag, str) or not feature_tag.endswith(suffix):
        raise base.OperationError("tag does not match Feature ID")
    prefix = feature_tag[:-len(suffix)]
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", prefix):
        raise base.OperationError("invalid feature tag name")
    if service not in ("console", "accounts", "billing") or base.domain(zone) != "onwalk.net":
        raise base.OperationError("unsupported SIT feature service or zone")
    label = feature_tag + '-sit' if service == 'console' else service + '-' + feature_tag + '-sit'
    if len(label) > 63:
        raise base.OperationError("SIT DNS label exceeds 63 characters")
    return base.domain(label + '.onwalk.net')


def requested_domain(env: dict, feature_id: str, service: str, zone: str) -> tuple[str, str | None]:
    operation = env.get('RESOURCE_OPERATION', 'sit-feature-dns')
    if operation == 'sit-feature-dns':
        if env.get('FEATURE_TAG') or env.get('FEATURE_HOSTNAME'):
            raise base.OperationError('legacy DNS operation cannot consume tagged inputs')
        return lane_domain(feature_id, service, zone), None
    if operation != 'sit-feature-tag-dns':
        raise base.OperationError('unsupported feature DNS operation')
    tag = base.required(env, 'FEATURE_TAG')
    hostname = tagged_lane_domain(feature_id, tag, service, zone)
    if base.required(env, 'FEATURE_HOSTNAME') != hostname:
        raise base.OperationError('candidate hostname does not match tag, feature and service')
    return hostname, tag


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
    def __init__(self, token: str, account_id: str, feature_id: str, feature_tag: str | None = None):
        super().__init__(token, account_id)
        self.feature_id = feature_id
        self.feature_tag = feature_tag

    def ownership_tags(self):
        tags = [f"feature-id:{self.feature_id}", "owner:iac-modules"]
        if self.feature_tag:
            tags.append(f"feature-tag:{self.feature_tag}")
        return sorted(tags)

    def records(self, zone_id: str, name: str) -> list[dict]:
        records = super().records(zone_id, name)
        if any(not set(self.ownership_tags()) <= set(r.get("tags") or []) for r in records):
            raise base.OperationError("DNS name is occupied by a record not owned by this Feature ID")
        return records

    def create_payload(self, payload: dict) -> dict:
        return dict(payload, comment=f"Codex SIT lane {self.feature_id}", tags=self.ownership_tags())

    def delete(self, zone_id: str, record_id: str) -> None:
        raise base.OperationError("DNS deletion requires an authenticated lane cleanup receipt; reconcile never deletes")


def main() -> int:
    try:
        feature_id = os.environ.get("FEATURE_ID", "").strip()
        service = os.environ.get("FEATURE_DNS_SERVICE", "").strip()
        zone = base.domain(base.required(os.environ, "DNS_ZONE"))
        if os.environ.get("DNS_ENVIRONMENT") != "sit":
            raise base.OperationError("feature DNS is SIT-only")
        name, tag = requested_domain(os.environ, feature_id, service, zone)
        cmdb = json.loads(Path(base.required(os.environ, "CMDB_FILE")).read_text())
        node = base.required(os.environ, "DEV_INGRESS_NODE")
        target = dev_ingress_ip(cmdb, node)
        env = dict(os.environ, DNS_ENVIRONMENT="sit", DNS_ZONE=zone, DNS_RECORD_NAME=name, DNS_TARGET_IP=target)
        config = base.Config.from_env(env, allowed_environments=("sit",))
        client = FeatureCloudflare(base.required(env, "CLOUDFLARE_DNS_API_TOKEN"), base.required(env, "CLOUDFLARE_ACCOUNT_ID"), feature_id, tag)
        result = base.execute(config, client)
        print(json.dumps({"result": "verified", "feature_id": feature_id, "feature_tag": tag, "service": service, "hostname": name, **result}, sort_keys=True))
        return 0
    except (base.OperationError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
