#!/usr/bin/env python3
"""UAT gateway single-A plan/apply/restore; no broad DNS cleanup or host work."""

import argparse
import copy
import fcntl
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class OperationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise OperationError(message)


def identity(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{32}", value),
            "Invalid provider identity")
    return value


def domain(value):
    require(isinstance(value, str) and len(value) <= 253 and value == value.lower()
            and len(value.split(".")) >= 2 and all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
                for part in value.split(".")), "Invalid DNS name")
    return value


def intent(value):
    fields = {"version", "environment", "run_id", "release_tag", "account_id",
              "zone_id", "zone_name", "owner_tag", "record", "expected_record_id"}
    require(isinstance(value, dict) and set(value) == fields, "Invalid intent fields")
    require(value["version"] == 1 and value["environment"] == "uat",
            "Only UAT gateway version 1 is supported")
    for key in ("run_id", "release_tag"):
        require(isinstance(value[key], str) and re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", value[key]),
                "Invalid run or release identity")
    identity(value["account_id"])
    identity(value["zone_id"])
    zone = domain(value["zone_name"])
    require(isinstance(value["owner_tag"], str) and
            re.fullmatch(r"owner:[a-z0-9-]{1,64}", value["owner_tag"]), "Invalid owner tag")
    record = value["record"]
    require(isinstance(record, dict) and set(record) == {"type", "name", "content", "ttl", "proxied"},
            "Exactly one explicit A record is required")
    name = domain(record["name"])
    require(name.endswith("." + zone) and record["type"] == "A", "Invalid zone or type")
    try:
        public = ipaddress.IPv4Address(record["content"]).is_global
    except (ValueError, TypeError):
        public = False
    require(public and type(record["ttl"]) is int and record["ttl"] == 60
            and record["proxied"] is False, "Gateway requires public IPv4, TTL 60, DNS-only")
    if value["expected_record_id"] is not None:
        identity(value["expected_record_id"])
    return copy.deepcopy(value)


def payload(record):
    require(isinstance(record, dict), "Invalid provider record")
    identity(record.get("id"))
    domain(record.get("name"))
    require(record.get("type") == "A", "Conflicting non-A record")
    try:
        ipaddress.IPv4Address(record["content"])
    except (KeyError, ValueError, TypeError):
        raise OperationError("Invalid provider A address") from None
    require(type(record.get("ttl")) is int and type(record.get("proxied")) is bool,
            "Incomplete provider record")
    comment, tags, settings = record.get("comment") or "", record.get("tags") or [], record.get("settings") or {}
    require(isinstance(comment, str) and isinstance(tags, list) and all(isinstance(tag, str) for tag in tags)
            and isinstance(settings, dict) and set(settings) <= {"ipv4_only", "ipv6_only"}
            and all(type(v) is bool for v in settings.values()), "Unsupported provider metadata")
    require(record.get("private_routing", False) is False, "Private routing is unsupported")
    return {**{key: record[key] for key in ("type", "name", "content", "ttl", "proxied")},
            "comment": comment, "tags": sorted(tags), "settings": copy.deepcopy(settings)}


def snapshot(record):
    return None if record is None else {"id": identity(record["id"]), "record": payload(record)}


class Cloudflare:
    def __init__(self, token):
        require(bool(token), "CLOUDFLARE_DNS_API_TOKEN is required")
        self.token = token

    def request(self, method, path, data=None):
        request = Request("https://api.cloudflare.com/client/v4" + path,
                          data=None if data is None else json.dumps(data).encode(), method=method,
                          headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=30) as response:
                result = json.load(response)
        except HTTPError as error:
            code = error.code
            error.close()
            raise OperationError(f"Cloudflare HTTP {code}; mutation outcome may be uncertain") from None
        except (URLError, TimeoutError, ValueError):
            raise OperationError("Cloudflare request failed; mutation outcome may be uncertain") from None
        require(isinstance(result, dict) and result.get("success") is True, "Cloudflare request rejected")
        return result

    def zone(self, zone_id):
        return self.request("GET", f"/zones/{zone_id}")["result"]

    def records(self, zone_id, name):
        response = self.request("GET", f"/zones/{zone_id}/dns_records?" + urlencode(
            {"name": name, "per_page": 100, "page": 1}))
        records = response.get("result")
        info = response.get("result_info") or {}
        require(isinstance(records, list) and len(records) < 100 and info.get("total_pages", 1) <= 1
                and info.get("total_count", len(records)) == len(records), "Incomplete DNS result set")
        return records

    def create(self, zone_id, record):
        return self.request("POST", f"/zones/{zone_id}/dns_records", record)["result"]

    def update(self, zone_id, record_id, record):
        return self.request("PUT", f"/zones/{zone_id}/dns_records/{record_id}", record)["result"]

    def delete(self, zone_id, record_id):
        result = self.request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")["result"]
        require(isinstance(result, dict) and result.get("id") == record_id, "Delete identity mismatch")


def bind_zone(client, spec):
    zone = client.zone(spec["zone_id"])
    require(isinstance(zone, dict) and zone.get("id") == spec["zone_id"]
            and zone.get("name") == spec["zone_name"] and zone.get("status") == "active"
            and (zone.get("account") or {}).get("id") == spec["account_id"], "Zone/account binding mismatch")


def current(client, spec):
    records = client.records(spec["zone_id"], spec["record"]["name"])
    require(isinstance(records, list) and len(records) <= 1, "Conflicting or duplicate DNS records")
    if not records:
        return None
    record = records[0]
    require(record.get("name") == spec["record"]["name"], "Record name mismatch")
    configured = snapshot(record)
    owners = {tag for tag in configured["record"]["tags"] if tag.startswith("owner:")}
    require(not owners or owners == {spec["owner_tag"]}, "Existing canonical owner must be preserved")
    return configured


def make_plan(spec, client):
    spec = intent(spec)
    bind_zone(client, spec)
    before = current(client, spec)
    require((None if before is None else before["id"]) == spec["expected_record_id"],
            "Expected record identity/absence mismatch")
    desired = copy.deepcopy(before["record"]) if before else {
        "comment": "", "tags": [spec["owner_tag"]], "settings": {}}
    desired.update(spec["record"])
    return {"version": 1, "intent": spec, "before": before, "desired": desired}


def validate_plan(plan):
    require(isinstance(plan, dict) and set(plan) == {"version", "intent", "before", "desired"}
            and plan["version"] == 1, "Invalid plan schema")
    spec = intent(plan["intent"])
    before = plan["before"]
    if before is not None:
        require(isinstance(before, dict) and set(before) == {"id", "record"}, "Invalid prior record")
        require(snapshot({**before["record"], "id": before["id"]}) == before, "Invalid prior record state")
        require(before["record"]["name"] == spec["record"]["name"], "Prior record name mismatch")
        owners = {tag for tag in before["record"]["tags"] if tag.startswith("owner:")}
        require(not owners or owners == {spec["owner_tag"]}, "Existing canonical owner must be preserved")
    require((None if before is None else before["id"]) == spec["expected_record_id"], "Plan identity mismatch")
    expected = copy.deepcopy(before["record"]) if before else {
        "comment": "", "tags": [spec["owner_tag"]], "settings": {}}
    expected.update(spec["record"])
    require(plan["desired"] == expected, "Plan changes unapproved record metadata")
    return spec


def private_path(path):
    path = Path(path)
    require(path.is_absolute() and path.parent.resolve() == path.parent and not path.is_symlink(),
            "Output path must be absolute and contain no symlinks")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(stat.S_IMODE(path.parent.stat().st_mode) & 0o077 == 0, "Output directory must be private (0700)")
    if path.exists():
        require(path.is_file() and stat.S_IMODE(path.stat().st_mode) == 0o600, "Output must be a private regular file")
    return path


def save(path, value):
    path = private_path(path)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        os.fchmod(handle.fileno(), 0o600)
        json.dump(value, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load(path):
    path = private_path(path)
    require(path.exists(), "Required file is missing")
    return json.loads(path.read_text())


@contextmanager
def checkpoint_lock(path):
    lock = private_path(str(path) + ".lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError:
        raise OperationError("Checkpoint operation already in progress") from None
    finally:
        os.close(fd)


def wait_for_dns(name, address, budget=120):
    deadline = time.monotonic() + budget
    while time.monotonic() < deadline:
        converged = True
        for resolver in ("1.1.1.1", "8.8.8.8"):
            try:
                result = subprocess.run(["dig", "+time=1", "+tries=1", "+short", "@" + resolver, name, "A"],
                                        capture_output=True, text=True, timeout=2, check=False)
                converged = converged and result.returncode == 0 and result.stdout.split() == [address]
            except (subprocess.TimeoutExpired, FileNotFoundError):
                converged = False
        if converged:
            return True
        time.sleep(max(0, min(5, deadline - time.monotonic())))
    return False


def receipt(spec, action, changed, record_id, resolver_verified=True):
    return {"version": 1, "action": action, "verified": True, "changed": changed,
            "provider_verified": True, "resolver_verified": resolver_verified, "host_acceptance": False,
            "environment": spec["environment"], "run_id": spec["run_id"], "release_tag": spec["release_tag"],
            "account_id": spec["account_id"], "zone_id": spec["zone_id"], "name": spec["record"]["name"],
            "record_id": record_id}


def checkpoint(plan, path):
    state = load(path)
    require(isinstance(state, dict) and set(state) == {"version", "plan", "record_id", "phase"}
            and state["version"] == 1 and state["plan"] == plan
            and state["phase"] in ("prepared", "applied", "verified", "restored"), "Checkpoint binding mismatch")
    if state["record_id"] is not None:
        identity(state["record_id"])
    if plan["before"] is not None:
        require(state["record_id"] == plan["before"]["id"], "Checkpoint record mismatch")
    return state


def apply(plan, client, path, waiter=wait_for_dns):
    spec = validate_plan(plan)
    bind_zone(client, spec)
    path = private_path(path)
    with checkpoint_lock(path):
        state = checkpoint(plan, path) if path.exists() else None
        require(state is None or state["phase"] != "restored", "Use a new operation after restore")
        observed = current(client, spec)
        if state is None:
            require(observed == plan["before"], "DNS changed after planning")
            state = {"version": 1, "plan": plan, "record_id": None if observed is None else observed["id"],
                     "phase": "prepared"}
            save(path, state)
        expected = None if state["record_id"] is None else {"id": state["record_id"], "record": plan["desired"]}
        if observed == plan["before"]:
            if observed is None:
                require(state["record_id"] is None, "Created record disappeared; refusing another create")
                result = client.create(spec["zone_id"], plan["desired"])
                state["record_id"] = identity(result.get("id") if isinstance(result, dict) else None)
                save(path, state)
            elif observed["record"] != plan["desired"]:
                client.update(spec["zone_id"], observed["id"], plan["desired"])
        else:
            require(expected is not None and observed == expected, "DNS changed or create outcome is uncertain")
        expected = {"id": state["record_id"], "record": plan["desired"]}
        require(current(client, spec) == expected, "Provider readback mismatch; checkpoint retained")
        state["phase"] = "applied"
        save(path, state)
        require(waiter(spec["record"]["name"], spec["record"]["content"]),
                "Resolver convergence failed; checkpoint retained")
        require(current(client, spec) == expected, "DNS changed during resolver wait")
        state["phase"] = "verified"
        save(path, state)
        return receipt(spec, "apply", plan["before"] != expected, state["record_id"])


def restore(plan, client, path, waiter=wait_for_dns):
    spec = validate_plan(plan)
    bind_zone(client, spec)
    with checkpoint_lock(path):
        state = checkpoint(plan, path)
        observed = current(client, spec)
        expected = None if state["record_id"] is None else {"id": state["record_id"], "record": plan["desired"]}
        changed = observed != plan["before"]
        if changed:
            require(expected is not None and observed == expected, "Refusing recovery after concurrent/uncertain change")
            if plan["before"] is None:
                client.delete(spec["zone_id"], state["record_id"])
            else:
                client.update(spec["zone_id"], state["record_id"], plan["before"]["record"])
        require(current(client, spec) == plan["before"], "Recovery readback mismatch")
        if plan["before"] is not None and not plan["before"]["record"]["proxied"]:
            require(waiter(spec["record"]["name"], plan["before"]["record"]["content"]),
                    "Recovered at provider; resolver recovery remains pending")
        # A created record's deletion is verified at the provider; cached DNS can outlive it.
        state["phase"] = "restored"
        save(path, state)
        return receipt(spec, "restore", changed, state["record_id"],
                       plan["before"] is not None and not plan["before"]["record"]["proxied"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    planner = sub.add_parser("plan")
    planner.add_argument("--intent", required=True)
    planner.add_argument("--output", required=True)
    for action in ("apply", "restore"):
        command = sub.add_parser(action)
        command.add_argument("--plan", required=True)
        command.add_argument("--checkpoint", required=True)
        command.add_argument("--receipt", required=True)
    args = parser.parse_args()
    try:
        if args.action == "plan":
            require(not Path(args.output).exists(), "Plan output already exists")
            spec = intent(load(args.intent))
            result = make_plan(spec, Cloudflare(os.environ.get("CLOUDFLARE_DNS_API_TOKEN")))
            save(args.output, result)
        else:
            plan = load(args.plan)
            validate_plan(plan)
            require(not Path(args.receipt).exists(), "Receipt output already exists; use a fresh path")
            require(len({str(Path(p).resolve()) for p in (args.plan, args.checkpoint, args.receipt)}) == 3,
                    "Plan, checkpoint and receipt must use distinct paths")
            result = globals()[args.action](plan, Cloudflare(os.environ.get("CLOUDFLARE_DNS_API_TOKEN")),
                                           Path(args.checkpoint))
            save(args.receipt, result)
        print(f"DNS {args.action} completed; no host/service acceptance implied")
        return 0
    except OperationError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    except (ValueError, OSError, KeyError, TypeError):
        # Do not echo caller JSON, provider responses or token-bearing exceptions.
        print("::error::DNS operation refused or failed; retain checkpoint and inspect sanitized evidence", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
