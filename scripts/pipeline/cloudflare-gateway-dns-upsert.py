#!/usr/bin/env python3
"""Guarded single-A upsert for an explicitly declared gateway DNS target.

This is an IaC/provider executor. It never reads GitOps, renders CMDB, probes
hosts, or starts services; the Toolkit supplies the resolved runtime plan.
"""

from __future__ import annotations

import fcntl
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class OperationError(RuntimeError):
    pass


def required(env: dict[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise OperationError(f"{key} is required")
    return value


def domain(value: str) -> str:
    value = value.lower().rstrip(".")
    labels = value.split(".")
    if len(value) > 253 or len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?[a-z0-9]?", label)
        for label in labels
    ):
        raise OperationError("invalid DNS name")
    return value


def public_ipv4(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise OperationError("DNS_TARGET_IP must be an IPv4 address") from None
    if address.version != 4 or address.is_private or address.is_loopback or address.is_reserved or address.is_multicast:
        raise OperationError("DNS_TARGET_IP must be a public IPv4 address")
    return str(address)


def record_payload(record: dict) -> dict:
    result = {key: record[key] for key in ("type", "name", "content", "ttl", "proxied")}
    result["comment"] = record.get("comment") or ""
    result["tags"] = sorted(record.get("tags") or [])
    if "settings" in record:
        result["settings"] = record["settings"]
    return result


@dataclass(frozen=True)
class Config:
    environment: str
    account_id: str
    zone: str
    name: str
    target: str
    checkpoint: Path
    resolver_wait: bool

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "Config":
        environment = required(env, "DNS_ENVIRONMENT")
        if environment not in ("uat", "prod"):
            raise OperationError("DNS_ENVIRONMENT must be uat or prod")
        account_id = required(env, "CLOUDFLARE_ACCOUNT_ID")
        if not re.fullmatch(r"[a-f0-9]{32}", account_id):
            raise OperationError("CLOUDFLARE_ACCOUNT_ID must be a 32-character id")
        zone = domain(required(env, "DNS_ZONE"))
        name = domain(required(env, "DNS_RECORD_NAME"))
        if name != zone and not name.endswith("." + zone):
            raise OperationError("DNS_RECORD_NAME must belong to DNS_ZONE")
        checkpoint = Path(required(env, "DNS_CHECKPOINT_PATH"))
        if not checkpoint.is_absolute() or checkpoint.is_symlink():
            raise OperationError("DNS_CHECKPOINT_PATH must be absolute and non-symlink")
        return cls(
            environment,
            account_id,
            zone,
            name,
            public_ipv4(required(env, "DNS_TARGET_IP")),
            checkpoint,
            env.get("DNS_WAIT_FOR_RESOLVER", "true").lower() == "true",
        )


class Cloudflare:
    def __init__(self, token: str, account_id: str):
        self.token = token
        self.account_id = account_id

    def request(self, method: str, path: str, payload: dict | None = None):
        body = None if payload is None else json.dumps(payload).encode()
        request = Request(
            "https://api.cloudflare.com/client/v4" + path,
            data=body,
            method=method,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                result = json.load(response)
        except HTTPError as error:
            raise OperationError(f"Cloudflare HTTP {error.code}") from None
        except (URLError, TimeoutError, ValueError):
            raise OperationError("Cloudflare request failed") from None
        if not isinstance(result, dict) or result.get("success") is not True:
            raise OperationError("Cloudflare rejected the DNS request")
        return result.get("result")

    def zone_id(self, zone: str) -> str:
        result = self.request("GET", "/zones?" + urlencode({"name": zone, "status": "active", "account.id": self.account_id}))
        if not isinstance(result, list) or len(result) != 1 or not result[0].get("id"):
            raise OperationError("expected exactly one active Cloudflare zone")
        return result[0]["id"]

    def records(self, zone_id: str, name: str) -> list[dict]:
        result = self.request("GET", f"/zones/{zone_id}/dns_records?" + urlencode({"name": name, "per_page": 100}))
        if not isinstance(result, list):
            raise OperationError("invalid Cloudflare DNS response")
        for record in result:
            if not isinstance(record, dict) or record.get("name") != name or not record.get("id"):
                raise OperationError("DNS record identity mismatch")
        return result

    def create(self, zone_id: str, payload: dict) -> dict:
        result = self.request("POST", f"/zones/{zone_id}/dns_records", payload)
        if not isinstance(result, dict) or not result.get("id"):
            raise OperationError("Cloudflare create returned no record id")
        return result

    def update(self, zone_id: str, record_id: str, payload: dict) -> dict:
        result = self.request("PUT", f"/zones/{zone_id}/dns_records/{record_id}", payload)
        if not isinstance(result, dict) or result.get("id") != record_id:
            raise OperationError("Cloudflare update returned an unexpected record")
        return result

    def delete(self, zone_id: str, record_id: str) -> None:
        self.request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")


def save_checkpoint(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        os.fchmod(handle.fileno(), 0o600)
        json.dump(state, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_checkpoint(config: Config) -> dict:
    try:
        state = json.loads(config.checkpoint.read_text())
    except (OSError, ValueError) as error:
        raise OperationError("invalid DNS checkpoint") from error
    if not isinstance(state, dict) or state.get("version") != 1:
        raise OperationError("unsupported DNS checkpoint")
    if any(state.get(key) != value for key, value in {
        "environment": config.environment, "account_id": config.account_id,
        "zone": config.zone, "name": config.name, "target": config.target,
    }.items()):
        raise OperationError("DNS checkpoint target mismatch")
    if state.get("action") not in ("create", "update", "noop"):
        raise OperationError("invalid DNS checkpoint action")
    return state


def wait_for_dns(name: str, address: str) -> bool:
    for attempt in range(1, 13):
        try:
            result = subprocess.run(
                ["dig", "+time=2", "+tries=1", "+short", "@1.1.1.1", name, "A"],
                capture_output=True, text=True, timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and result.returncode == 0 and address in result.stdout.split():
            return True
        if attempt < 12:
            time.sleep(5)
    return False


def restore(config: Config, client: Cloudflare, state: dict) -> None:
    zone_id = state["zone_id"]
    records = client.records(zone_id, config.name)
    current = next((record for record in records if record.get("id") == state.get("record_id")), None)
    if state["action"] == "create":
        if current is None:
            return
        if record_payload(current) != state["desired"]:
            raise OperationError("refusing restore: created DNS record changed")
        client.delete(zone_id, current["id"])
        return
    if current is None or record_payload(current) != state["desired"]:
        raise OperationError("refusing restore: updated DNS record changed")
    client.update(zone_id, current["id"], state["original"])


def execute(config: Config, client: Cloudflare, waiter=wait_for_dns) -> dict:
    lock_path = config.checkpoint.with_name(config.checkpoint.name + ".lock")
    lock_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return _execute_locked(config, client, waiter)


def _execute_locked(config: Config, client: Cloudflare, waiter=wait_for_dns) -> dict:
    zone_id = client.zone_id(config.zone)
    records = client.records(zone_id, config.name)
    if any(record.get("type") != "A" for record in records):
        raise OperationError("conflicting non-A DNS record exists")
    if len(records) > 1:
        raise OperationError("multiple A DNS records exist; refusing implicit cleanup")
    if not records:
        desired = {"type": "A", "name": config.name, "content": config.target, "ttl": 60, "proxied": False, "comment": "", "tags": []}
        action, record_id, original = "create", None, None
    else:
        original = record_payload(records[0])
        desired = dict(original, content=config.target, ttl=60, proxied=False)
        if original == desired:
            action, record_id = "noop", records[0]["id"]
        else:
            action, record_id = "update", records[0]["id"]
    state = {"version": 1, "environment": config.environment, "account_id": config.account_id,
             "zone": config.zone, "name": config.name, "target": config.target,
             "zone_id": zone_id, "record_id": record_id, "action": action,
             "original": original, "desired": desired}
    previous = load_checkpoint(config) if config.checkpoint.exists() else None
    if previous is not None:
        if previous["desired"] != desired or previous["zone_id"] != zone_id:
            raise OperationError("existing DNS checkpoint does not match current plan")
        if previous["action"] == "create":
            if action == "noop" and previous.get("record_id") == record_id:
                state = previous
                action = "noop"
            elif action == "create":
                state = previous
            else:
                raise OperationError("DNS state changed after a create checkpoint")
        elif previous["action"] == "update":
            if action == "noop" and previous.get("record_id") == record_id:
                state = previous
                action = "noop"
            elif action == "update" and original in (previous["original"], previous["desired"]):
                state = previous
            else:
                raise OperationError("DNS state changed after an update checkpoint")
        elif previous["action"] == "noop" and action == "noop":
            state = previous
        else:
            raise OperationError("DNS checkpoint action changed")
    else:
        save_checkpoint(config.checkpoint, state)
    if action == "create" and state.get("record_id") is None:
        created = client.create(zone_id, desired)
        state["record_id"] = created["id"]
        save_checkpoint(config.checkpoint, state)
    elif action == "update" and original == state["original"]:
        client.update(zone_id, record_id, desired)
    if config.resolver_wait and not waiter(config.name, config.target):
        try:
            restore(config, client, state)
        except OperationError as recovery:
            raise OperationError(f"resolver convergence failed; recovery failed: {recovery}") from None
        raise OperationError("resolver convergence failed; previous DNS state restored")
    return {"changed": action != "noop", "action": action, "record_id": state["record_id"], "address": config.target}


def main() -> int:
    try:
        config = Config.from_env(os.environ)
        result = execute(config, Cloudflare(required(os.environ, "CLOUDFLARE_DNS_API_TOKEN"), config.account_id))
        print(f"Cloudflare DNS {result['action']} verified for {config.name}: {result['address']}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as output:
                for key, value in result.items():
                    output.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
        return 0
    except (OperationError, ValueError, OSError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
