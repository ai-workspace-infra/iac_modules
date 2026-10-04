#!/usr/bin/env python3
"""Read-only inventory of legacy UAT Akamai state and matching Linode resources."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


NAMESPACES = (
    "web-saas",
    "open-platform",
    "ai-workspace",
    "agent-proxy-jp",
    "agent-proxy-us",
    "agent-proxy-sg",
)
CLEANUP_NAMESPACES = (
    "web-saas",
    "ai-workspace",
    "agent-proxy-jp",
    "agent-proxy-us",
    "agent-proxy-sg",
)
PROTECTED_SOURCE = "observability.svc.plus"


def legacy_state_candidates(account: str) -> tuple[dict[str, str], ...]:
    return (
        {
            "state_key": f"terraform/uat/platform-ops-toolkit/akamai-cloud/{account}/selfhost/terraform.tfstate",
            "source_commit": "77d3a51f5b39f420ebee4fe07a22b442ddd3b206",
            "source_path": ".github/scripts/platform-ops/provision/platform-ops_provision_route-ref-to-an-explicit-profile.sh",
            "derivation": "historical UAT Akamai target_domains=all -> selfhost",
        },
    )


LINODE_API = "https://api.linode.com/v4"
READ_ONLY_TERRAFORM_COMMANDS = {
    ("init",),
    ("show",),
}
READ_ONLY_AWS_COMMANDS = {
    ("s3api", "list-object-versions"),
    ("s3api", "head-object"),
}
LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")


class PreflightError(RuntimeError):
    """An error with a safe, non-secret message suitable for the job summary."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _load_generator(iac_root: Path):
    generator_path = (
        iac_root
        / "terraform-hcl-standard"
        / "akamai-cloud"
        / "scripts"
        / "generate.py"
    )
    if not generator_path.is_file():
        raise PreflightError("iac_generator_missing")
    generator_dir = str(generator_path.parent)
    if generator_dir not in sys.path:
        sys.path.insert(0, generator_dir)
    spec = importlib.util.spec_from_file_location("akamai_iac_generate", generator_path)
    if spec is None or spec.loader is None:
        raise PreflightError("iac_generator_unloadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_manifest_expectations(gitops_root: Path, iac_root: Path) -> list[dict[str, Any]]:
    """Use the checked-out main-branch renderer to derive the exact Linode labels."""
    generator = _load_generator(iac_root)
    expectations = []
    for namespace in NAMESPACES:
        relative = Path("resources/svc.plus/uat/akamai") / f"{namespace}.yaml"
        manifest = gitops_root / relative
        if not manifest.is_file():
            raise PreflightError(f"manifest_missing:{namespace}")
        try:
            global_config, _ssh_keys, hosts = generator.load_sources(str(manifest))
        except Exception as exc:  # Renderer errors can include expanded YAML values.
            raise PreflightError(f"manifest_parse_failed:{namespace}") from exc
        if len(hosts) != 1:
            raise PreflightError(f"manifest_host_count_invalid:{namespace}")
        # The new Open Platform node legitimately serves the public
        # observability.svc.plus endpoint after migration.  Only fail when the
        # protected legacy source is declared as the Terraform-managed host
        # identity; service_domains and other routing metadata are allowed to
        # reference that endpoint.
        managed_identity = {
            str(hosts[0].get(key, "")).strip().casefold()
            for key in ("name", "label", "hostname", "instance_label")
        }
        if PROTECTED_SOURCE.casefold() in managed_identity:
            raise PreflightError(f"protected_source_as_managed_host:{namespace}")
        declared_namespace = str(global_config.get("state_namespace", "")).strip()
        if declared_namespace != namespace:
            raise PreflightError(f"manifest_namespace_mismatch:{namespace}")
        label = str(hosts[0].get("label", ""))
        firewall_label = str(generator.firewall_label(label))
        if not LABEL_PATTERN.fullmatch(label) or not LABEL_PATTERN.fullmatch(firewall_label):
            raise PreflightError(f"manifest_label_invalid:{namespace}")
        expectations.append(
            {
                "namespace": namespace,
                "manifest": relative.as_posix(),
                "label": label,
                "firewall_label": firewall_label,
                "region": str(hosts[0].get("region") or global_config.get("region") or ""),
                "type": str(hosts[0].get("type", hosts[0].get("plan", "")) or ""),
            }
        )
    return expectations


def _terraform_call(root: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    command_shape = tuple(args[:2]) if args[:1] == ["state"] else tuple(args[:1])
    if command_shape not in READ_ONLY_TERRAFORM_COMMANDS:
        raise PreflightError("terraform_command_not_allowlisted")
    return subprocess.run(
        ["terraform", f"-chdir={root}", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _backend_hcl(state_key: str, env: dict[str, str]) -> str:
    required = (
        "TF_STATE_ENDPOINT",
        "TF_STATE_BUCKET",
        "TF_STATE_ACCESS_KEY",
        "TF_STATE_SECRET_KEY",
        "TF_STATE_REGION",
    )
    if any(not env.get(name) for name in required):
        raise PreflightError("terraform_state_credentials_missing")
    if not env["TF_STATE_ENDPOINT"].startswith(("https://", "http://")):
        raise PreflightError("terraform_state_endpoint_invalid")
    strings = {
        "bucket": env["TF_STATE_BUCKET"],
        "key": state_key,
        "region": env["TF_STATE_REGION"],
        "access_key": env["TF_STATE_ACCESS_KEY"],
        "secret_key": env["TF_STATE_SECRET_KEY"],
    }
    lines = [f"{key} = {json.dumps(value)}" for key, value in strings.items()]
    lines.extend(
        [
            f"endpoints = {{ s3 = {json.dumps(env['TF_STATE_ENDPOINT'])} }}",
            "skip_credentials_validation = true",
            "skip_region_validation = true",
            "skip_requesting_account_id = true",
            "skip_metadata_api_check = true",
            "skip_s3_checksum = true",
            "use_path_style = true",
            # terraform show -json is read-only and does not create an S3 lock object.
            "use_lockfile = false",
            'workspace_key_prefix = "env"',
        ]
    )
    return "\n".join(lines) + "\n"


def _is_missing_state(result: subprocess.CompletedProcess[str]) -> bool:
    message = f"{result.stdout}\n{result.stderr}".casefold()
    return any(
        marker in message
        for marker in (
            "no state file was found",
            "state file was not found",
            "state file does not exist",
        )
    )


def _resource_values(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        return {}
    values = document.get("values") or document.get("attributes") or {}
    return values if isinstance(values, dict) else {}


def parse_terraform_show_json(output: str) -> tuple[list[dict[str, Any]], bool, bool]:
    """Project managed resources from terraform show -json without retaining payloads."""
    protected = PROTECTED_SOURCE in output.casefold()
    try:
        document = json.loads(output)
    except json.JSONDecodeError as exc:
        raise PreflightError("terraform_show_json_invalid") from exc
    if not isinstance(document, dict):
        raise PreflightError("terraform_show_json_invalid")
    values = document.get("values")
    root_module = values.get("root_module") if isinstance(values, dict) else None
    if root_module is None:
        return [], protected, False
    if not isinstance(root_module, dict):
        raise PreflightError("terraform_show_root_module_invalid")

    resources: list[dict[str, Any]] = []

    def visit_module(module: dict[str, Any]) -> None:
        module_resources = module.get("resources", [])
        child_modules = module.get("child_modules", [])
        if not isinstance(module_resources, list) or not isinstance(child_modules, list):
            raise PreflightError("terraform_show_module_invalid")
        for item in module_resources:
            if not isinstance(item, dict) or item.get("mode", "managed") != "managed":
                continue
            address = str(item.get("address", ""))
            resource_type = str(item.get("type", ""))
            resource_values = item.get("values")
            if not address or not resource_type or not isinstance(resource_values, dict):
                raise PreflightError("terraform_show_resource_invalid")
            resource_id = str(resource_values.get("id", "") or "")
            label_value = resource_values.get("label")
            label = str(label_value) if label_value is not None else ""
            identity = hashlib.sha256(
                json.dumps(
                    [resource_type, resource_id, label, address if not resource_id else ""],
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            resource = {
                "address": address,
                "resource_type": resource_type,
                "identity_sha256": identity,
                "identity_complete": bool(resource_id),
            }
            if resource_type in {"linode_instance", "linode_firewall"}:
                if not resource_id:
                    raise PreflightError("terraform_state_resource_id_missing")
                if not resource_id.isdecimal():
                    raise PreflightError("terraform_state_resource_id_invalid")
                if not LABEL_PATTERN.fullmatch(label):
                    raise PreflightError("terraform_state_resource_label_invalid")
                resource.update({"id": resource_id, "label": label})
            resources.append(resource)
        for child in child_modules:
            if not isinstance(child, dict):
                raise PreflightError("terraform_show_child_module_invalid")
            visit_module(child)

    visit_module(root_module)
    return resources, protected, True


def inspect_terraform_state(state_key: str, backend_env: dict[str, str]) -> dict[str, Any]:
    """Initialize a disposable backend config and read state via terraform show -json."""
    with tempfile.TemporaryDirectory(prefix="akamai-state-read-") as temporary:
        root = Path(temporary)
        (root / "main.tf").write_text(
            'terraform {\n  backend "s3" {}\n}\n',
            encoding="utf-8",
        )
        backend_file = root / "backend.hcl"
        backend_file.write_text(_backend_hcl(state_key, backend_env), encoding="utf-8")
        backend_file.chmod(0o600)
        env = dict(backend_env)
        env.update({"TF_IN_AUTOMATION": "1", "CHECKPOINT_DISABLE": "1"})
        initialized = _terraform_call(
            root,
            ["init", "-input=false", "-no-color", "-reconfigure", f"-backend-config={backend_file}"],
            env,
        )
        if initialized.returncode:
            raise PreflightError("terraform_backend_read_init_failed")
        shown = _terraform_call(root, ["show", "-json"], env)
        if shown.returncode:
            if _is_missing_state(shown):
                return {"state_key": state_key, "present": False, "resources": [], "protected_text": False}
            raise PreflightError("terraform_show_failed")
        resources, protected, state_present = parse_terraform_show_json(shown.stdout)
        return {
            "state_key": state_key,
            "present": state_present,
            "resources": resources,
            "protected_text": protected,
        }


def _aws_readonly(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    if tuple(args[:2]) not in READ_ONLY_AWS_COMMANDS:
        raise PreflightError("aws_command_not_allowlisted")
    return subprocess.run(
        ["aws", *args, "--no-cli-pager"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def inspect_legacy_object_versions(state_key: str, env: dict[str, str], account: str) -> dict[str, Any]:
    """Read version metadata and an archive object's headers; never copy/delete."""
    required = (
        "TF_STATE_ENDPOINT",
        "TF_STATE_BUCKET",
        "TF_STATE_ACCESS_KEY",
        "TF_STATE_SECRET_KEY",
        "TF_STATE_REGION",
    )
    if any(not env.get(name) for name in required):
        raise PreflightError("terraform_state_credentials_missing")
    aws_env = dict(env)
    aws_env.update(
        {
            "AWS_ACCESS_KEY_ID": env["TF_STATE_ACCESS_KEY"],
            "AWS_SECRET_ACCESS_KEY": env["TF_STATE_SECRET_KEY"],
            "AWS_DEFAULT_REGION": env["TF_STATE_REGION"],
            "AWS_REGION": env["TF_STATE_REGION"],
            "AWS_PAGER": "",
        }
    )
    base = [
        "s3api",
        "list-object-versions",
        "--bucket",
        env["TF_STATE_BUCKET"],
        "--prefix",
        state_key,
        "--endpoint-url",
        env["TF_STATE_ENDPOINT"],
        "--output",
        "json",
    ]
    try:
        result = _aws_readonly(base, aws_env)
    except FileNotFoundError:
        result = subprocess.CompletedProcess(["aws"], 127, "", "aws_cli_missing")
    if result.returncode:
        return {
            "state_key": state_key,
            "version_inventory_status": "unavailable",
            "version_inventory_error": "read_failed",
            "object_present": False,
            "versioning_enabled": False,
            "current_version": None,
            "previous_version_count": 0,
            "versions": [],
            "suggested_archive_key": f"terraform/archive/uat/platform-ops-toolkit/akamai-cloud/{account}/selfhost/terraform.tfstate",
            "archive_object": {"present": False, "matches_current_version_metadata": False},
            "backup_prerequisite_satisfied": False,
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "state_key": state_key,
            "version_inventory_status": "unavailable",
            "version_inventory_error": "invalid_response",
            "object_present": False,
            "versioning_enabled": False,
            "current_version": None,
            "previous_version_count": 0,
            "versions": [],
            "suggested_archive_key": f"terraform/archive/uat/platform-ops-toolkit/akamai-cloud/{account}/selfhost/terraform.tfstate",
            "archive_object": {"present": False, "matches_current_version_metadata": False},
            "backup_prerequisite_satisfied": False,
        }
    versions = [
        {
            "version_id": str(item.get("VersionId", "")),
            "is_latest": bool(item.get("IsLatest", False)),
            "last_modified": str(item.get("LastModified", "")),
            "size": int(item.get("Size", 0)),
            "etag": str(item.get("ETag", "")).strip('"'),
        }
        for item in payload.get("Versions", [])
        if item.get("Key") == state_key
    ]
    versions.sort(key=lambda item: (not item["is_latest"], item["last_modified"]))
    current = next((item for item in versions if item["is_latest"]), versions[0] if versions else None)
    versioning_enabled = any(item["version_id"] not in {"", "null"} for item in versions)
    archive_key = (
        "terraform/archive/uat/platform-ops-toolkit/akamai-cloud/"
        f"{account}/selfhost/terraform.tfstate"
    )
    archive = {
        "present": False,
        "matches_current_version_metadata": False,
        "check_status": "not-checked",
    }
    if current is not None:
        try:
            head = _aws_readonly(
                [
                "s3api",
                "head-object",
                "--bucket",
                env["TF_STATE_BUCKET"],
                "--key",
                archive_key,
                "--endpoint-url",
                env["TF_STATE_ENDPOINT"],
                "--output",
                "json",
                ],
                aws_env,
            )
        except FileNotFoundError:
            head = subprocess.CompletedProcess(["aws"], 127, "", "aws_cli_missing")
        if head.returncode == 0:
            try:
                metadata = json.loads(head.stdout)
            except json.JSONDecodeError as exc:
                raise PreflightError("legacy_state_archive_metadata_invalid") from exc
            archive = {
                "present": True,
                "check_status": "available",
                "version_id": str(metadata.get("VersionId", "")),
                "size": int(metadata.get("ContentLength", 0)),
                "etag": str(metadata.get("ETag", "")).strip('"'),
                "matches_current_version_metadata": (
                    int(metadata.get("ContentLength", -1)) == current["size"]
                    and str(metadata.get("ETag", "")).strip('"') == current["etag"]
                ),
            }
        elif not any(marker in head.stderr.casefold() for marker in ("404", "nosuchkey", "not found")):
            archive["check_status"] = "unavailable"
        else:
            archive["check_status"] = "available"
    else:
        archive["check_status"] = "available"
    previous_versions = max(0, len(versions) - (1 if current else 0))
    return {
        "state_key": state_key,
        "version_inventory_status": "available",
        "object_present": bool(versions),
        "versioning_enabled": versioning_enabled,
        "current_version": current,
        "previous_version_count": previous_versions,
        "versions": versions,
        "suggested_archive_key": archive_key,
        "archive_object": archive,
        "backup_prerequisite_satisfied": bool(
            versioning_enabled
            and current is not None
            and current["version_id"] not in {"", "null"}
            and (previous_versions > 0 or archive["matches_current_version_metadata"])
        ),
    }


def linode_get_pages(resource_path: str, token: str) -> list[dict[str, Any]]:
    if resource_path not in {"linode/instances", "networking/firewalls"}:
        raise PreflightError("linode_endpoint_not_allowlisted")
    # Vault values written from shell input can retain a trailing newline.
    # Normalize only surrounding whitespace and fail closed if any control
    # character remains inside the bearer token.
    token = token.strip()
    if not token or any(ord(character) < 32 or ord(character) == 127 for character in token):
        raise PreflightError("linode_token_invalid")
    results: list[dict[str, Any]] = []
    page = 1
    while True:
        query = urlencode({"page": page, "page_size": 500})
        request = Request(
            f"{LINODE_API}/{resource_path}?{query}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise PreflightError(f"linode_api_http_{exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise PreflightError("linode_api_read_failed") from exc
        data = payload.get("data")
        if not isinstance(data, list):
            raise PreflightError("linode_api_response_invalid")
        results.extend(item for item in data if isinstance(item, dict))
        pages = int(payload.get("pages", 1) or 0)
        if page >= pages:
            break
        page += 1
        if page > 100:
            raise PreflightError("linode_api_page_limit_exceeded")
    return results


def _project_live(items: list[dict[str, Any]], resource_type: str) -> list[dict[str, Any]]:
    projected = []
    for item in items:
        if not isinstance(item.get("label"), str):
            continue
        identifier = str(item.get("id", ""))
        if not identifier.isdecimal():
            raise PreflightError("linode_resource_id_invalid")
        record = {"id": identifier, "label": item["label"]}
        if resource_type == "linode_instance":
            for key in ("region", "type", "status"):
                value = item.get(key)
                if isinstance(value, (str, int, float, bool)):
                    record[key] = value
        else:
            value = item.get("status")
            if isinstance(value, (str, int, float, bool)):
                record["status"] = value
        projected.append(record)
    return projected


def _one_by_label(items: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    return [item for item in items if item.get("label") == label]


def _classify_namespace(
    expected: dict[str, Any],
    live_instances: list[dict[str, Any]],
    live_firewalls: list[dict[str, Any]],
    legacy_resources: list[dict[str, Any]],
    namespace_resources: list[dict[str, Any]],
) -> dict[str, Any]:
    namespace = expected["namespace"]
    live_instance = _one_by_label(live_instances, expected["label"])
    live_firewall = _one_by_label(live_firewalls, expected["firewall_label"])
    state_instances = [
        item for item in legacy_resources
        if item.get("resource_type") == "linode_instance" and item.get("label") == expected["label"]
    ]
    state_firewalls = [
        item for item in legacy_resources
        if item.get("resource_type") == "linode_firewall" and item.get("label") == expected["firewall_label"]
    ]
    target_instances = [
        item for item in namespace_resources
        if item.get("resource_type") == "linode_instance" and item.get("label") == expected["label"]
    ]
    target_firewalls = [
        item for item in namespace_resources
        if item.get("resource_type") == "linode_firewall" and item.get("label") == expected["firewall_label"]
    ]
    failures = []
    expected_live_instance_ids = {record["id"] for record in live_instance}
    expected_live_firewall_ids = {record["id"] for record in live_firewall}
    if any(
        item.get("resource_type") == "linode_instance"
        and item.get("id") in expected_live_instance_ids
        and item.get("label") != expected["label"]
        for item in legacy_resources
    ):
        failures.append("legacy_state_instance_id_label_mismatch")
    if any(
        item.get("resource_type") == "linode_firewall"
        and item.get("id") in expected_live_firewall_ids
        and item.get("label") != expected["firewall_label"]
        for item in legacy_resources
    ):
        failures.append("legacy_state_firewall_id_label_mismatch")
    if any(
        item.get("resource_type") == "linode_instance"
        and item.get("id") in expected_live_instance_ids
        and item.get("label") != expected["label"]
        for item in namespace_resources
    ):
        failures.append("namespace_state_instance_id_label_mismatch")
    if any(
        item.get("resource_type") == "linode_firewall"
        and item.get("id") in expected_live_firewall_ids
        and item.get("label") != expected["firewall_label"]
        for item in namespace_resources
    ):
        failures.append("namespace_state_firewall_id_label_mismatch")
    if len(live_instance) > 1 or len(live_firewall) > 1:
        failures.append("duplicate_live_label")
    if len(state_instances) > 1 or len(state_firewalls) > 1:
        failures.append("duplicate_legacy_state_label")
    if len(target_instances) > 1 or len(target_firewalls) > 1:
        failures.append("duplicate_namespace_state_label")
    if state_instances and live_instance and state_instances[0]["id"] != live_instance[0]["id"]:
        failures.append("legacy_state_instance_id_mismatch")
    if state_firewalls and live_firewall and state_firewalls[0]["id"] != live_firewall[0]["id"]:
        failures.append("legacy_state_firewall_id_mismatch")
    if target_instances and live_instance and target_instances[0]["id"] != live_instance[0]["id"]:
        failures.append("namespace_state_instance_id_mismatch")
    if target_firewalls and live_firewall and target_firewalls[0]["id"] != live_firewall[0]["id"]:
        failures.append("namespace_state_firewall_id_mismatch")
    if (state_instances and not live_instance) or (state_firewalls and not live_firewall):
        failures.append("state_resource_missing_from_linode_api")
    if (target_instances and not live_instance) or (target_firewalls and not live_firewall):
        failures.append("namespace_state_resource_missing_from_linode_api")
    if live_firewall and not live_instance:
        failures.append("orphan_firewall")
    if state_firewalls and live_instance and not state_instances:
        failures.append("firewall_only_in_legacy_state")
    if target_firewalls and live_instance and not target_instances:
        failures.append("firewall_only_in_namespace_state")

    if failures:
        status = "ambiguous"
        recommendation = "stop-and-reconcile-manually"
    elif live_instance and state_instances:
        status = "existing-in-legacy-state"
        recommendation = "adopt-from-legacy-state-after-reviewed-state-migration"
    elif live_instance and target_instances:
        status = "existing-in-namespace-state"
        recommendation = "verify-current-namespace-plan-without-reimport"
    elif live_instance:
        status = "existing-unmanaged"
        recommendation = "import-existing-resource-after-namespace-ownership-review"
    elif state_instances or state_firewalls or target_instances or target_firewalls or live_firewall:
        status = "ambiguous"
        recommendation = "stop-and-reconcile-manually"
        failures.append("partial_resource_set")
    else:
        status = "absent"
        recommendation = "plan-create-in-namespace-after-review"

    return {
        "namespace": namespace,
        "manifest": expected["manifest"],
        "expected_label": expected["label"],
        "expected_firewall_label": expected["firewall_label"],
        "region": expected["region"],
        "type": expected["type"],
        "status": status,
        "persistent": namespace == "open-platform",
        "cleanup_eligible": namespace in CLEANUP_NAMESPACES,
        "live_instances": live_instance,
        "live_firewalls": live_firewall,
        "legacy_state_instances": state_instances,
        "legacy_state_firewalls": state_firewalls,
        "namespace_state_instances": target_instances,
        "namespace_state_firewalls": target_firewalls,
        "recommendation": recommendation,
        "findings": failures,
    }


def build_report(
    expectations: list[dict[str, Any]],
    live_instances_raw: list[dict[str, Any]],
    live_firewalls_raw: list[dict[str, Any]],
    state_results: list[dict[str, Any]],
    legacy_object_versions: dict[str, Any] | None = None,
    account: str = "",
    correlation_id: str = "",
) -> dict[str, Any]:
    candidates = legacy_state_candidates(account)
    live_instances = _project_live(live_instances_raw, "linode_instance")
    live_firewalls = _project_live(live_firewalls_raw, "linode_firewall")
    legacy_state = next(
        (result for result in state_results if result["state_key"] == candidates[0]["state_key"]),
        {"state_key": candidates[0]["state_key"], "present": False, "resources": [], "protected_text": False},
    )
    namespace_states = {
        result["namespace"]: result for result in state_results if result.get("namespace")
    }
    state_resources = legacy_state["resources"]
    failures: list[str] = []
    if "open-platform" in CLEANUP_NAMESPACES:
        failures.append("open_platform_in_cleanup_scope")
    labels = [item["label"] for item in expectations]
    fw_labels = [item["firewall_label"] for item in expectations]
    if len(set(labels)) != len(labels) or len(set(fw_labels)) != len(fw_labels):
        failures.append("duplicate_manifest_label_across_namespaces")
    if any(result["protected_text"] for result in state_results):
        failures.append("protected_source_present_in_akamai_state")

    items = [
        _classify_namespace(
            item,
            live_instances,
            live_firewalls,
            state_resources,
            namespace_states.get(item["namespace"], {}).get("resources", []),
        )
        for item in expectations
    ]
    for item in items:
        if item["status"] == "ambiguous":
            failures.append(f"namespace_ambiguous:{item['namespace']}")

    id_owners: dict[tuple[str, str], set[str]] = {}
    for item in items:
        for resource_type, collection in (
            (
                "linode_instance",
                item["live_instances"] + item["legacy_state_instances"] + item["namespace_state_instances"],
            ),
            (
                "linode_firewall",
                item["live_firewalls"] + item["legacy_state_firewalls"] + item["namespace_state_firewalls"],
            ),
        ):
            for record in collection:
                if record.get("id"):
                    id_owners.setdefault((resource_type, record["id"]), set()).add(item["namespace"])
    duplicated_ids = [owners for owners in id_owners.values() if len(owners) > 1]
    if duplicated_ids:
        failures.append("resource_id_maps_to_multiple_namespaces")
        for item in items:
            if any(item["namespace"] in owners for owners in duplicated_ids):
                item["status"] = "ambiguous"
                item["recommendation"] = "stop-and-reconcile-manually"
                item["findings"].append("resource_id_maps_to_multiple_namespaces")
    if any(item["namespace"] == "open-platform" and item["cleanup_eligible"] for item in items):
        failures.append("open_platform_in_cleanup_scope")

    expected_owner = {
        ("linode_instance", item["label"]): item["namespace"] for item in expectations
    }
    expected_owner.update(
        {("linode_firewall", item["firewall_label"]): item["namespace"] for item in expectations}
    )
    target_resource_owners: dict[tuple[str, str], set[str]] = {}
    for namespace, result in namespace_states.items():
        for resource in result["resources"]:
            owner = expected_owner.get((resource.get("resource_type"), resource.get("label", "")))
            if owner is not None and owner != namespace:
                failures.append("namespace_state_resource_in_wrong_namespace")
                for item in items:
                    if item["namespace"] in {owner, namespace}:
                        item["status"] = "ambiguous"
                        item["recommendation"] = "stop-and-reconcile-manually"
                        item["findings"].append("namespace_state_resource_in_wrong_namespace")
            if resource.get("id"):
                target_resource_owners.setdefault(
                    (resource.get("resource_type", ""), resource["id"]), set()
                ).add(namespace)
    if any(len(owners) > 1 for owners in target_resource_owners.values()):
        failures.append("resource_id_maps_to_multiple_namespaces")

    target_by_identity: dict[str, list[dict[str, Any]]] = {}
    for namespace, result in namespace_states.items():
        for resource in result["resources"]:
            target_by_identity.setdefault(resource["identity_sha256"], []).append(
                {**resource, "namespace": namespace, "state_key": result["state_key"]}
            )
    expected_namespace_by_label = {}
    for expectation in expectations:
        expected_namespace_by_label[("linode_instance", expectation["label"])] = expectation["namespace"]
        expected_namespace_by_label[("linode_firewall", expectation["firewall_label"])] = expectation["namespace"]
    legacy_identity_counts: dict[str, int] = {}
    for resource in state_resources:
        legacy_identity_counts[resource["identity_sha256"]] = legacy_identity_counts.get(resource["identity_sha256"], 0) + 1
    mappings = []
    unmapped = 0
    duplicates = 0
    namespace_mismatches = 0
    for resource in state_resources:
        matches = target_by_identity.get(resource["identity_sha256"], [])
        record = {
            "legacy_address": resource["address"],
            "resource_type": resource["resource_type"],
            "identity_sha256": resource["identity_sha256"],
        }
        if resource["resource_type"] in {"linode_instance", "linode_firewall"}:
            record["id"] = resource["id"]
            record["label"] = resource["label"]
        if (
            resource.get("identity_complete")
            and len(matches) == 1
            and matches[0].get("identity_complete")
            and legacy_identity_counts[resource["identity_sha256"]] == 1
        ):
            target = matches[0]
            expected_namespace = expected_namespace_by_label.get(
                (resource["resource_type"], resource.get("label", ""))
            )
            mapping_status = (
                "namespace-mismatch"
                if expected_namespace is not None and target["namespace"] != expected_namespace
                else "one-to-one"
            )
            record.update(
                {
                    "mapping_status": mapping_status,
                    "target_namespace": target["namespace"],
                    "target_state_key": target["state_key"],
                    "target_address": target["address"],
                }
            )
            if mapping_status == "namespace-mismatch":
                namespace_mismatches += 1
        elif len(matches) > 1 or legacy_identity_counts[resource["identity_sha256"]] > 1:
            duplicates += 1
            record.update({"mapping_status": "duplicate", "target_matches": len(matches)})
        else:
            unmapped += 1
            record.update({"mapping_status": "unmapped", "target_matches": 0})
        mappings.append(record)
    if duplicates:
        failures.append("legacy_resource_maps_to_multiple_target_states")
    if namespace_mismatches:
        failures.append("legacy_resource_mapped_to_wrong_namespace")

    object_versions = legacy_object_versions or {
        "state_key": candidates[0]["state_key"],
        "version_inventory_status": "not-checked",
        "object_present": False,
        "versioning_enabled": False,
        "current_version": None,
        "previous_version_count": 0,
        "versions": [],
        "suggested_archive_key": f"terraform/archive/uat/platform-ops-toolkit/akamai-cloud/{account}/selfhost/terraform.tfstate",
        "archive_object": {"present": False, "matches_current_version_metadata": False, "check_status": "not-checked"},
        "backup_prerequisite_satisfied": False,
    }
    retirement_plan = {
        "legacy_state_key": candidates[0]["state_key"],
        "legacy_state_present": legacy_state["present"] or bool(object_versions["object_present"]),
        "object_versions": object_versions,
        "resource_mappings": mappings,
        "mapping_counts": {
            "legacy_resource_count": len(state_resources),
            "one_to_one": sum(item["mapping_status"] == "one-to-one" for item in mappings),
            "unmapped": unmapped,
            "duplicate": duplicates,
            "namespace_mismatch": namespace_mismatches,
        },
        "retirement_prerequisites": {
            "all_six_namespace_plans_zero_add_change_destroy": "required",
            "every_legacy_resource_has_one_to_one_namespace_mapping": "required",
            "migration_acceptance_complete": "required",
            "old_observability_source_unchanged_through_acceptance": "required",
            "versioned_or_verified_archive_backup": "required",
        },
        "state_rm_or_retire_allowed": False,
        "suggested_archive_key": object_versions["suggested_archive_key"],
    }
    if object_versions["version_inventory_status"] == "unavailable":
        failures.append("legacy_state_version_inventory_unavailable")
    if object_versions.get("archive_object", {}).get("check_status") == "unavailable":
        failures.append("legacy_state_archive_check_unavailable")
    return {
        "schema_version": 1,
        "mode": "read-only",
        "environment": "uat",
        "account": account,
        "correlation_id": correlation_id,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "failed" if failures else "complete",
        "failures": sorted(set(failures)),
        "legacy_state_candidates": [
            {
                "state_key": candidate["state_key"],
                "source_commit": candidate["source_commit"],
                "source_path": candidate["source_path"],
                "present": legacy_state["present"] or bool(object_versions["object_present"]),
            }
            for candidate in candidates
        ],
        "future_cleanup_namespaces": list(CLEANUP_NAMESPACES),
        "namespaces": items,
        "retirement_plan": retirement_plan,
    }


def write_outputs(report: dict[str, Any], output_path: Path, summary_path: str | None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not summary_path:
        return
    lines = [
        "## Akamai UAT migration preflight (read-only)",
        "",
        f"Result: **{report['status']}** · environment: `uat` · account: `{report['account']}` · correlation: `{report['correlation_id']}`",
        "",
        "| Namespace | Status | Expected Linode label | Live instance IDs | Legacy state IDs | Next step |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in report["namespaces"]:
        live = ", ".join(record["id"] for record in item["live_instances"]) or "—"
        state = ", ".join(record["id"] for record in item["legacy_state_instances"]) or "—"
        lines.append(
            f"| `{item['namespace']}` | `{item['status']}` | `{item['expected_label']}` | `{live}` | `{state}` | `{item['recommendation']}` |"
        )
    lines.extend(["", f"Sanitized JSON: `{output_path.name}`", ""])
    retirement = report.get("retirement_plan", {})
    counts = retirement.get("mapping_counts", {})
    versions = retirement.get("object_versions", {})
    current_version = versions.get("current_version") or {}
    lines.extend(
        [
            "### Legacy state retirement preview",
            "",
            f"- Legacy key: `{retirement.get('legacy_state_key', 'unavailable')}`",
            f"- Current object version: `{current_version.get('version_id', 'unavailable')}`; versioning: `{versions.get('versioning_enabled', False)}`; archive prerequisite: `{versions.get('backup_prerequisite_satisfied', False)}`",
            f"- Resource mapping counts: one-to-one `{counts.get('one_to_one', 0)}`, unmapped `{counts.get('unmapped', 0)}`, duplicate `{counts.get('duplicate', 0)}`, namespace mismatch `{counts.get('namespace_mismatch', 0)}`",
            f"- Suggested archive key: `{retirement.get('suggested_archive_key', 'unavailable')}`",
            "- State retirement/removal allowed by this workflow: **false**",
            "",
        ]
    )
    if report["failures"]:
        lines.extend(["Invariant failures:", "", *[f"- `{failure}`" for failure in report["failures"]], ""])
    with open(summary_path, "a", encoding="utf-8") as summary:
        summary.write("\n".join(lines) + "\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    expectations = load_manifest_expectations(Path(args.gitops_root), Path(args.iac_root))
    token = os.environ.get("LINODE_TOKEN", "")
    if not token:
        raise PreflightError("linode_token_missing")
    backend_env = dict(os.environ)
    state_results = []
    candidates = legacy_state_candidates(args.account)
    for candidate in candidates:
        legacy_state = inspect_terraform_state(candidate["state_key"], backend_env)
        legacy_state["scope"] = "legacy"
        state_results.append(legacy_state)
    state_project = "svc.plus"
    provider = "akamai-cloud"
    account = args.account
    namespace_state_keys = {
        namespace: f"terraform/uat/{state_project}/{provider}/{account}/{namespace}/terraform.tfstate"
        for namespace in NAMESPACES
    }
    for namespace, state_key in namespace_state_keys.items():
        state = inspect_terraform_state(state_key, backend_env)
        state["namespace"] = namespace
        state_results.append(state)
    object_versions = inspect_legacy_object_versions(candidates[0]["state_key"], backend_env, account)
    instances = linode_get_pages("linode/instances", token)
    firewalls = linode_get_pages("networking/firewalls", token)
    return build_report(expectations, instances, firewalls, state_results, object_versions, account, args.correlation_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gitops-root", required=True)
    parser.add_argument("--iac-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--environment", required=True, choices=("uat",))
    parser.add_argument("--account", required=True)
    parser.add_argument("--correlation-id", required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}", args.account):
        parser.error("--account must be a safe account identifier")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", args.correlation_id):
        parser.error("--correlation-id must be a safe correlation identifier")
    output = Path(args.output)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    try:
        report = run(args)
    except PreflightError as exc:
        report = {
            "schema_version": 1,
            "mode": "read-only",
            "environment": "uat",
            "account": args.account,
            "correlation_id": args.correlation_id,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "status": "failed",
            "failures": [exc.code],
            "namespaces": [],
        }
    write_outputs(report, output, summary)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
