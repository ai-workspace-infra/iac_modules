#!/usr/bin/env python3
"""Small shared writer for the IaC -> Playbooks CMDB contract.

The top-level host keys are intentionally retained for older callers that use
``jq '.<host>.ip'``. New consumers should read ``hosts`` and validate
``schema_version`` first.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "cmdb.v1"
SUPPORTED_ENVIRONMENTS = {"dev", "sit", "uat", "prod", "shared"}
SECRET_KEY = re.compile(r"(?:password|token|secret|private[_-]?key|credential)", re.IGNORECASE)


def infer_environment(resource_paths: str | list[str], explicit: str | None = None) -> str:
    """Resolve the environment from an explicit value or a GitOps path."""
    candidate = (explicit or os.environ.get("DEPLOY_ENVIRONMENT", "")).strip()
    if candidate in SUPPORTED_ENVIRONMENTS:
        return candidate

    paths = resource_paths if isinstance(resource_paths, list) else resource_paths.split(",")
    for raw_path in paths:
        parts = Path(raw_path.strip()).parts
        for part in parts:
            if part in SUPPORTED_ENVIRONMENTS:
                return part
    return "unknown"


def resource_refs(resource_paths: str | list[str]) -> list[str]:
    """Keep provenance portable without embedding a workstation absolute path."""
    paths = resource_paths if isinstance(resource_paths, list) else resource_paths.split(",")
    refs = []
    for raw_path in paths:
        path = raw_path.strip()
        marker = "resources/"
        refs.append(path[path.index(marker):] if marker in path else Path(path).name)
    return refs


def make_document(
    hosts: Mapping[str, Mapping[str, Any]],
    *,
    cloud_provider: str,
    resource_paths: str | list[str],
    project_id: str | None = None,
    environment: str | None = None,
    legacy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a cmdb.v1 document while preserving legacy top-level records."""
    for name, host in hosts.items():
        for key in (host.get("host_vars", {}) or {}):
            if SECRET_KEY.search(str(key)):
                raise ValueError(
                    f"CMDB host {name} contains secret-like host_vars key {key!r}; "
                    "runtime credentials must stay outside the CMDB"
                )

    document: dict[str, Any] = dict(legacy or {})
    document.update(
        {
            "schema_version": SCHEMA_VERSION,
            "environment": infer_environment(resource_paths, environment),
            "cloud_provider": cloud_provider,
            "source_resources": resource_refs(resource_paths),
            "hosts": dict(hosts),
        }
    )
    if project_id:
        document["project_id"] = project_id

    # Compatibility for existing scripts and receipts. The canonical path is
    # document["hosts"], but old callers may still use document[host_name].
    for name, host in hosts.items():
        document[name] = host
    return document


def write_document(path: str | os.PathLike[str], document: Mapping[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
