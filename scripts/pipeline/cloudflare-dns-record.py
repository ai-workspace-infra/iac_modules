#!/usr/bin/env python3
"""Manage one reviewed A record with a guarded runner-local recovery checkpoint."""

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


def required(env, key):
    value = env.get(key, "").strip()
    if not value:
        raise OperationError(f"{key} is required")
    return value


def domain(value):
    value = value.lower()
    labels = value.split(".")
    if len(value) > 253 or len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        raise OperationError("Invalid DNS zone or record name")
    return value


@dataclass
class Config:
    environment: str
    zone: str
    name: str
    action: str
    source: str
    target: str
    checkpoint: Path

    @classmethod
    def from_env(cls, env):
        environment = required(env, "DNS_ENVIRONMENT")
        if environment not in ("uat", "prod"):
            raise OperationError("DNS_ENVIRONMENT must be uat or prod")
        zone = domain(required(env, "DNS_ZONE"))
        name = domain(required(env, "DNS_RECORD_NAME"))
        if name != zone and not name.endswith("." + zone):
            raise OperationError("DNS_RECORD_NAME must belong to DNS_ZONE")
        action = required(env, "DNS_ACTION")
        if action not in ("cutover", "rollback", "restore"):
            raise OperationError("Unsupported DNS_ACTION")
        source = env.get("SOURCE_IP", "")
        target = env.get("TARGET_IP", "")
        if action != "restore":
            ipaddress.IPv4Address(required(env, "SOURCE_IP"))
            if target:
                ipaddress.IPv4Address(target)
            if action == "cutover":
                ipaddress.IPv4Address(required(env, "TARGET_IP"))
                if source == target:
                    raise OperationError("Source and target addresses must differ")
        checkpoint = Path(required(env, "DNS_CHECKPOINT_PATH"))
        if not checkpoint.is_absolute() or checkpoint.is_symlink():
            raise OperationError("DNS_CHECKPOINT_PATH must be an absolute, non-symlink path")
        return cls(environment, zone, name, action, source, target, checkpoint)


class Cloudflare:
    def __init__(self, token):
        self.token = token

    def request(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(
            "https://api.cloudflare.com/client/v4" + path,
            data=data,
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

    def zone_id(self, zone):
        zones = self.request("GET", "/zones?" + urlencode({"name": zone, "status": "active"}))
        if not isinstance(zones, list) or len(zones) != 1 or not zones[0].get("id"):
            raise OperationError("Expected exactly one active DNS zone")
        return zones[0]["id"]

    def record(self, zone_id, name):
        records = self.request("GET", f"/zones/{zone_id}/dns_records?" + urlencode(
            {"type": "A", "name": name, "per_page": 100}
        ))
        if not isinstance(records, list) or len(records) != 1:
            raise OperationError("Expected exactly one A record")
        record = records[0]
        if record.get("name") != name or record.get("type") != "A" or not record.get("id"):
            raise OperationError("DNS record identity mismatch")
        try:
            ipaddress.IPv4Address(record["content"])
            record_payload(record)
        except (KeyError, ValueError, TypeError):
            raise OperationError("Invalid Cloudflare A record") from None
        return record

    def update(self, zone_id, record_id, payload):
        self.request("PUT", f"/zones/{zone_id}/dns_records/{record_id}", payload)


def record_payload(record):
    result = {key: record[key] for key in ("type", "name", "content", "ttl", "proxied")}
    result.update(comment=record.get("comment") or "", tags=sorted(record.get("tags") or []))
    if "settings" in record:
        result["settings"] = record["settings"]
    return result


def save_checkpoint(path, state):
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


def load_checkpoint(config):
    state = json.loads(config.checkpoint.read_text())
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or state.get("environment") != config.environment
        or state.get("zone") != config.zone
        or state.get("name") != config.name
    ):
        raise OperationError("DNS checkpoint environment or target mismatch")
    for key in ("zone_id", "record_id", "original", "desired", "changed"):
        if key not in state:
            raise OperationError("Incomplete DNS checkpoint")
    if not isinstance(state["changed"], bool):
        raise OperationError("Invalid DNS checkpoint mutation state")
    for key in ("zone_id", "record_id"):
        if not isinstance(state[key], str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", state[key]):
            raise OperationError("Invalid DNS checkpoint resource identity")
    for key in ("original", "desired"):
        payload = state[key]
        if not isinstance(payload, dict) or payload.get("name") != config.name or payload.get("type") != "A":
            raise OperationError("Invalid DNS checkpoint record binding")
        try:
            ipaddress.IPv4Address(payload["content"])
            if not isinstance(payload["ttl"], int) or not isinstance(payload["proxied"], bool):
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise OperationError("Invalid DNS checkpoint record state") from None
    return state


def wait_for_dns(name, address):
    for attempt in range(1, 31):
        converged = True
        for resolver in ("1.1.1.1", "8.8.8.8", "9.9.9.9"):
            try:
                result = subprocess.run(
                    ["dig", "+time=2", "+tries=1", "+short", "@" + resolver, name, "A"],
                    capture_output=True, text=True, timeout=5, check=False,
                )
                answers = result.stdout.split()
                converged = converged and result.returncode == 0 and address in answers
            except subprocess.TimeoutExpired:
                converged = False
            print(f"DNS resolver={resolver} attempt={attempt} converged={converged}", flush=True)
        if converged:
            return True
        if attempt < 30:
            time.sleep(10)
    return False


def restore(config, client, waiter, state):
    current = client.record(state["zone_id"], config.name)
    if current["id"] != state["record_id"]:
        raise OperationError("Refusing restore: DNS record identity changed")
    if not state["changed"] or record_payload(current) == state["original"]:
        return False
    if record_payload(current) != state["desired"]:
        raise OperationError("Refusing restore: DNS record changed after this operation")
    client.update(state["zone_id"], state["record_id"], state["original"])
    verified = client.record(state["zone_id"], config.name)
    if record_payload(verified) != state["original"]:
        raise OperationError("DNS restore did not reach the saved record state")
    if not state["original"]["proxied"] and not waiter(config.name, state["original"]["content"]):
        raise OperationError("DNS restored at the provider; resolver propagation remains pending")
    print(f"Restored DNS record {config.name} from the release checkpoint")
    return True


def execute(config, client, waiter=wait_for_dns):
    if config.action == "restore":
        state = load_checkpoint(config)
        changed = restore(config, client, waiter, state)
        return {"changed": changed, "record_id": state["record_id"], "address": state["original"]["content"]}

    zone_id = client.zone_id(config.zone)
    current = client.record(zone_id, config.name)
    desired_ip = config.target if config.action == "cutover" else config.source
    expected_ip = config.source if config.action == "cutover" else config.target
    already_desired = config.action == "cutover" and current["content"] == desired_ip
    if not already_desired:
        if expected_ip and current["content"] != expected_ip:
            raise OperationError("Refusing DNS change: current address differs from the expected address")
        if not expected_ip and current["content"] == desired_ip:
            raise OperationError("DNS rollback is already at the source address")
    original = record_payload(current)
    desired = dict(original, content=desired_ip, ttl=60, proxied=False)
    state = {
        "version": 1, "environment": config.environment, "zone": config.zone, "name": config.name,
        "zone_id": zone_id, "record_id": current["id"], "action": config.action,
        "original": original, "desired": desired, "changed": not already_desired,
    }
    if config.checkpoint.exists():
        previous = load_checkpoint(config)
        if previous.get("action") != config.action or previous["desired"]["content"] != desired_ip:
            raise OperationError("Refusing to overwrite an unrelated DNS checkpoint")
        if previous["zone_id"] != zone_id or previous["record_id"] != current["id"]:
            raise OperationError("DNS checkpoint resource identity mismatch")
        if original not in (previous["original"], previous["desired"]):
            raise OperationError("DNS state changed since the saved checkpoint")
        state = previous
    else:
        save_checkpoint(config.checkpoint, state)
    try:
        if not already_desired:
            client.update(zone_id, current["id"], state["desired"])
        if not waiter(config.name, desired_ip):
            raise OperationError("DNS resolver convergence timed out")
        verified = client.record(zone_id, config.name)
        if verified["id"] != current["id"] or verified["content"] != desired_ip or verified["proxied"]:
            raise OperationError("DNS provider verification failed")
    except OperationError as failure:
        if config.action == "cutover":
            try:
                restore(config, client, waiter, state)
            except OperationError as recovery:
                raise OperationError(f"{failure}; recovery: {recovery}") from None
            raise OperationError(f"{failure}; original DNS state restored") from None
        raise
    return {"changed": state["changed"], "record_id": current["id"], "address": desired_ip}


def main():
    try:
        config = Config.from_env(os.environ)
        result = execute(config, Cloudflare(required(os.environ, "CLOUDFLARE_DNS_API_TOKEN")))
        print(f"DNS {config.action} verified for {config.name}: {result['address']}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as handle:
                for key, value in result.items():
                    handle.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
        return 0
    except (OperationError, ValueError, OSError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
