#!/usr/bin/env python3
"""Guarded create/update for a single SIT Cloudflare A record in svc.plus."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import importlib.util

spec = importlib.util.spec_from_file_location("sit_dns_base", Path(__file__).with_name("cloudflare-gateway-dns-upsert.py"))
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)


def main() -> int:
    try:
        config = base.Config.from_env(os.environ, allowed_environments=("sit",), allow_underscores=True)
        if config.zone != "svc.plus":
            raise base.OperationError("SIT desktop DNS is restricted to the svc.plus zone")
        expected = os.environ.get("DNS_EXPECTED_CURRENT_IP", "").strip()
        client = base.Cloudflare(base.required(os.environ, "CLOUDFLARE_DNS_API_TOKEN"), config.account_id)
        zone_id = client.zone_id(config.zone)
        records = client.records(zone_id, config.name)
        if expected:
            try:
                base.ipaddress.IPv4Address(expected)
            except ValueError:
                raise base.OperationError("DNS_EXPECTED_CURRENT_IP must be IPv4") from None
        if len(records) > 1 or any(record.get("type") != "A" for record in records):
            raise base.OperationError("conflicting or duplicate DNS records exist")
        if records and records[0].get("content") != expected:
            raise base.OperationError("existing DNS A record does not match DNS_EXPECTED_CURRENT_IP")
        if not records and expected:
            raise base.OperationError("DNS_EXPECTED_CURRENT_IP was set but no A record exists")
        result = base.execute(config, client)
        print(f"SIT Cloudflare DNS {result['action']} verified for {config.name}: {result['address']}")
        return 0
    except (base.OperationError, ValueError, OSError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
