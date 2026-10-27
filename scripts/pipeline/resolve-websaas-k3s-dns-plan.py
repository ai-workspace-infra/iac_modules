#!/usr/bin/env python3
"""Resolve the reviewed PROD Web-SaaS K3s CNAME plan from GitOps topology."""
import json
from pathlib import Path
import sys

import yaml


EXPECTED = {
    "console.svc.plus": ("console-selfhost-prod-v5.svc.plus", "console-k3s-v5.svc.plus"),
    "accounts.svc.plus": ("accounts-selfhost-prod-v5.svc.plus", "accounts-k3s-v5.svc.plus"),
    "billing.svc.plus": ("billing-selfhost-prod-v5.svc.plus", "billing-k3s-v5.svc.plus"),
}


def resolve(path: Path) -> dict:
    config = yaml.safe_load(path.read_text())
    dns = config["spec"]["runtime"]["routing"]["dns"]
    domains = config["spec"]["domains"]
    if config.get("kind") != "EdgeRoutingConfig" or config["metadata"].get("environment") != "prod":
        raise ValueError("expected a PROD EdgeRoutingConfig")
    if dns.get("control_plane") != "cloudflare-dns":
        raise ValueError("unexpected DNS owner")
    if dns.get("canonical_records", {}).get("postgresql.svc.plus") != "postgresql-selfhost-prod-v5.svc.plus":
        raise ValueError("PostgreSQL canonical record must remain unchanged")

    rows = []
    for name, (expected_source, target) in EXPECTED.items():
        if dns.get("canonical_records", {}).get(name) != target:
            raise ValueError(f"GitOps target mismatch for {name}")
        if domains.get(name, {}).get("selfhost") != target:
            raise ValueError(f"selfhost domain mismatch for {name}")
        if name in ("accounts.svc.plus", "billing.svc.plus"):
            if dns.get("api_cname_records", {}).get(name, {}).get("selfhost") != target:
                raise ValueError(f"API alias target mismatch for {name}")
        rows.append({
            "zone": "svc.plus",
            "name": name,
            "type": "CNAME",
            "expected_content": expected_source,
            "content": target,
        })
    return {"environment": "prod", "records": rows}


if __name__ == "__main__":
    try:
        print(json.dumps(resolve(Path(sys.argv[1])), separators=(",", ":")))
    except (IndexError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"DNS plan rejected: {exc}", file=sys.stderr)
        sys.exit(2)
