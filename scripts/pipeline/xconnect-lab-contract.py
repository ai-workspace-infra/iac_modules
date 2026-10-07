#!/usr/bin/env python3
"""Render and guard the provider-owned XConnect lab Terraform contract."""

from __future__ import annotations

import datetime
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
import uuid


STATE_PREFIX = "terraform/uat/svc.plus/aws-cloud/primary/xconnect-lab"


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    path.chmod(0o600)


def state_key(run: str) -> str:
    if not re.fullmatch(r"xcl-[0-9]+-[0-9]+", run):
        raise ValueError("run identity is invalid")
    return f"{STATE_PREFIX}/{run}/terraform.tfstate"


def cidrs(value: str, label: str) -> list[str]:
    result = [] if not value.strip() else [item.strip() for item in value.split(",")]
    if len(result) > 2 or len(result) != len(set(result)):
        raise ValueError(f"{label} must contain at most two unique IPv4 /32 values")
    for item in result:
        parsed = ipaddress.ip_interface(item)
        if parsed.version != 4 or parsed.network.prefixlen != 32 or str(parsed) != item:
            raise ValueError(f"{label} must contain canonical IPv4 /32 values")
    return result


def base_values(spec: dict, run: str, provider: str) -> dict:
    return {
        "run_id": run,
        "gateway_provider": provider,
        "aws_region": spec["aws"]["region"],
        "aws_client_instance_type": spec["nodes"]["one"]["instance_type"],
        "aws_gateway_instance_type": spec["nodes"]["gateway"]["instance_type"],
        "zero_accounts_api_url": spec["zero"]["accounts_api_url"],
        "zero_portal_url": spec["zero"]["portal_url"],
    }


def guard_cleanup(folder: Path, run: str) -> None:
    root = json.loads((folder / "state.json").read_text()).get("values", {}).get("root_module", {})
    if root.get("child_modules"):
        raise ValueError("unexpected nested module in dedicated lab state")
    allowed = {"aws_security_group.client", "aws_security_group.gateway",
               "aws_instance.client", "aws_instance.gateway"}
    for resource in root.get("resources", []):
        if resource.get("mode") == "data":
            continue
        address = re.sub(r"\[0\]$", "", resource.get("address", ""))
        if address not in allowed:
            raise ValueError("unexpected resource in lab state")
        values = resource.get("values", {})
        if resource.get("type", "").startswith("aws_") and "tags_all" in values:
            if values["tags_all"].get("LabRun") != run:
                raise ValueError("AWS lab ownership mismatch")


def render(action: str, folder: Path, declaration: Path, environment: dict[str, str]) -> None:
    spec = json.loads(declaration.read_text())["spec"]
    run = environment["TF_VAR_run_id"]
    state_key(run)
    provider = environment.get("GATEWAY_PROVIDER", spec["gateway_provider"]).strip()
    if provider not in {"aws-spot", "external"}:
        raise ValueError("gateway provider is invalid")
    if action == "backend":
        save(folder / "backend.json", {
            "bucket": environment["TF_STATE_BUCKET"], "key": state_key(run),
            "region": environment["TF_STATE_REGION"],
            "endpoints": {"s3": environment["TF_STATE_ENDPOINT"]},
            "access_key": environment["TF_STATE_ACCESS_KEY"],
            "secret_key": environment["TF_STATE_SECRET_KEY"], "token": "",
            "skip_credentials_validation": True, "skip_region_validation": True,
            "skip_requesting_account_id": True, "skip_metadata_api_check": True,
            "use_path_style": True, "use_lockfile": True,
        })
        return
    values = base_values(spec, run, provider)
    if action == "resources":
        uuid.UUID(environment["LAB_VLESS_ID"])
        if len(environment["ZERO_SERVICE_TOKEN"]) < 32:
            raise ValueError("runtime service token is invalid")
        owner = environment["ZERO_OWNER_EMAIL"].strip()
        if "@" not in owner or owner.startswith("@") or owner.endswith("@"):
            raise ValueError("runtime owner email is invalid")
        transport = spec.get("gateway_transport", {})
        if (transport.get("enabled") is not True or transport.get("port") != 443
                or transport.get("transport") != "vless-xhttp"
                or transport.get("public_wireguard_ingress") is not False):
            raise ValueError("gateway transport policy is incompatible")
        transport_cidrs = cidrs(environment.get("GATEWAY_TRANSPORT_INGRESS_CIDRS", ""), "gateway transport ingress")
        ssh_cidrs = cidrs(environment.get("SSH_DEBUG_INGRESS_CIDRS", ""), "SSH debug ingress")
        ami = subprocess.check_output([
            "aws", "ssm", "get-parameter", "--name", spec["aws"]["ami_ssm_parameter"],
            "--query", "Parameter.Value", "--output", "text"], text=True).strip()
        images = json.loads(subprocess.check_output([
            "aws", "ec2", "describe-images", "--image-ids", ami, "--output", "json"]))["Images"]
        if len(images) != 1 or images[0].get("Architecture") != "arm64" or images[0].get("OwnerId") != "099720109477":
            raise ValueError("expected Canonical ARM64 Ubuntu AMI")
        with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=15) as response:
            runner_ip = str(ipaddress.IPv4Address(response.read().decode().strip()))
        values.update(
            aws_ami=ami, runner_cidr=runner_ip + "/32",
            ssh_public_key=(folder / "id_ed25519.pub").read_text().strip(),
            gateway_transport_ingress_cidrs=transport_cidrs,
            ssh_debug_ingress_cidrs=ssh_cidrs,
            expires_at=(datetime.datetime.now(datetime.timezone.utc)
                        + datetime.timedelta(minutes=spec["ttl_minutes"])).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        if provider == "external":
            address = ipaddress.ip_address(environment.get("EXTERNAL_GATEWAY_HOST", ""))
            if address.version != 4:
                raise ValueError("external Gateway must be IPv4")
            values["external_gateway_ip"] = str(address)
    elif action == "cleanup":
        guard_cleanup(folder, run)
        values.update(aws_ami="ami-unused-for-destroy", runner_cidr="127.0.0.1/32",
                      ssh_public_key="unused-for-destroy", gateway_transport_ingress_cidrs=[],
                      ssh_debug_ingress_cidrs=[], expires_at="1970-01-01T00:00:00Z")
        if provider == "external":
            values["external_gateway_ip"] = environment.get("EXTERNAL_GATEWAY_HOST", "127.0.0.1")
    else:
        raise ValueError("unknown render operation")
    save(folder / "variables.json", values)


def main() -> int:
    try:
        action, folder, declaration = sys.argv[1:]
        render(action, Path(folder), Path(declaration), dict(os.environ))
        return 0
    except Exception as error:
        print(f"XConnect lab IaC contract failed ({type(error).__name__}); inspect owner-private evidence.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
