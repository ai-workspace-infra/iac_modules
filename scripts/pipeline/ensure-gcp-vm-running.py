#!/usr/bin/env python3
"""Reconcile the runtime state of GitOps-declared GCP VMs.

Terraform treats an existing, stopped Spot VM as an in-sync resource.  That
is correct for state ownership but not sufficient for the following SSH
deployment stage.  This small, apply-only reconciliation starts only the
instances present in the rendered resource manifest and waits for GCP to
report RUNNING.  It never creates, replaces, or deletes an instance.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path


def gcloud(*args: str) -> str:
    command = ["gcloud", *args, "--format=value(status)"]
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()


def report_stop(project: str, name: str, zone: str) -> None:
    # Keep the operator-visible stop time and operation type, never the acting
    # principal. Failure to list operations must not prevent recovery.
    timestamp = subprocess.check_output(
        ["gcloud", "compute", "instances", "describe", name, "--project", project,
         "--zone", zone, "--format=value(lastStopTimestamp,lastSuspendedTimestamp)"],
        text=True, stderr=subprocess.STDOUT,
    ).strip()
    print(f"GCP VM {name} stop record: {timestamp}")
    operations = subprocess.run(
        ["gcloud", "compute", "operations", "list", "--project", project,
         "--zones", zone, f"--filter=targetLink~/instances/{name}$", "--sort-by=~insertTime",
         "--limit=5", "--format=value(insertTime,operationType,status)"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
    )
    if operations.returncode == 0:
        print(f"Recent operations on {name}:\n{operations.stdout.strip()}")
    else:
        print(f"::warning::Could not list GCP operations for {name}; check Cloud Audit Logs for the stop cause")


def instance_specs(manifest: dict) -> list[tuple[str, str]]:
    specs: list[tuple[str, str]] = []
    for key in ("vault_nodes", "spot_vms"):
        for item in manifest.get(key, []) or []:
            name, zone = item.get("name"), item.get("zone")
            if not name or not zone:
                raise SystemExit(f"{key} entries require name and zone")
            specs.append((str(name), str(zone)))
    if not specs:
        raise SystemExit("resource manifest contains no GCP VMs")
    if len(set(specs)) != len(specs):
        raise SystemExit("resource manifest contains duplicate GCP VM identities")
    return specs


def reconcile(project: str, specs: list[tuple[str, str]], timeout: int, interval: int) -> list[str]:
    deadline = time.monotonic() + timeout
    started: list[str] = []
    for name, zone in specs:
        status = gcloud("compute", "instances", "describe", name, "--project", project, "--zone", zone)
        print(f"GCP VM {name} ({zone}) status={status or 'unknown'}")
        if status in {"TERMINATED", "STOPPED", "SUSPENDED"}:
            operation = "resume" if status == "SUSPENDED" else "start"
            report_stop(project, name, zone)
            print(f"Requesting {operation} for existing GCP VM {name}; no resource creation is requested.")
            subprocess.check_call(
                ["gcloud", "compute", "instances", operation, name, "--project", project, "--zone", zone, "--quiet"]
            )
            started.append(name)

    while True:
        pending = []
        for name, zone in specs:
            status = gcloud("compute", "instances", "describe", name, "--project", project, "--zone", zone)
            if status != "RUNNING":
                pending.append(f"{name}={status or 'unknown'}")
        if not pending:
            print("All declared GCP VMs are RUNNING.")
            return started
        if time.monotonic() >= deadline:
            raise SystemExit(f"GCP VMs did not become RUNNING within {timeout}s: {', '.join(pending)}")
        print(f"Waiting for GCP VM runtime readiness: {', '.join(pending)}")
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--manifest", type=Path)
    target.add_argument("--instance")
    parser.add_argument("--zone")
    parser.add_argument("--project", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--interval", type=int, default=5)
    args = parser.parse_args()
    if args.timeout < 1 or args.interval < 1:
        raise SystemExit("timeout and interval must be positive")
    if args.instance:
        if not args.zone or not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", args.instance) or not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", args.zone):
            raise SystemExit("a declared instance and zone are required")
        specs = [(args.instance, args.zone)]
    else:
        if args.zone:
            raise SystemExit("--zone requires --instance")
        specs = instance_specs(json.loads(args.manifest.read_text(encoding="utf-8")))
    started = reconcile(args.project, specs, args.timeout, args.interval)
    # A Spot VM that was stopped when Terraform refreshed has no ephemeral
    # public IP in state; tell the workflow to refresh before the inventory.
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"started={'true' if started else 'false'}\n")


if __name__ == "__main__":
    main()
