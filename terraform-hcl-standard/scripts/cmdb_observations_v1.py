#!/usr/bin/env python3
"""Validate provider-neutral observed inventory envelopes before persistence.

Provider adapters must return a complete/partial run receipt and normalized
resource observations. This module deliberately performs no cloud API calls,
database writes, Terraform operations, or secret lookup.
"""

from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any, Mapping
from urllib.parse import quote


SCHEMA_VERSION = "cmdb.observations.v1"
SCOPES = {"shared", "sit", "uat", "prod", "unknown"}
SOURCES = {"provider_api", "external_inventory"}
OUTCOMES = {"success", "partial", "failed"}
SECRET_KEY = re.compile(
    r"(?:password|token|secret|private[_-]?key|credential|authorization|"
    r"user[_-]?data|startup[_-]?script|environment[_-]?variables?)",
    re.IGNORECASE,
)


class ContractError(ValueError):
    """Raised when an observation envelope violates the CMDB contract."""


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    return value.strip()


def _timestamp(value: Any, field: str) -> None:
    text = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{field} must include a timezone")


def _reject_secret_keys(value: Any, path: str = "observation") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if SECRET_KEY.search(str(key)):
                raise ContractError(f"secret-bearing field is not allowed: {path}.{key}")
            _reject_secret_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_keys(child, f"{path}[{index}]")


def canonical_id(observation: Mapping[str, Any]) -> str:
    """Return a stable provider identity; names and IP addresses are excluded."""
    parts = (
        _required_text(observation.get("provider"), "provider").lower(),
        str(observation.get("account_ref", "")).strip(),
        str(observation.get("project_ref", "")).strip(),
        _required_text(observation.get("resource_kind"), "resource_kind").lower(),
        _required_text(observation.get("native_resource_id"), "native_resource_id"),
    )
    return "cmdb://" + "/".join(quote(part, safe="") or "_" for part in parts)


def validate_envelope(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a JSON-compatible copy of an observations envelope."""
    if not isinstance(document, Mapping):
        raise ContractError("envelope must be an object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ContractError(f"schema_version must be {SCHEMA_VERSION}")

    run = document.get("run")
    observations = document.get("observations")
    if not isinstance(run, Mapping):
        raise ContractError("run must be an object")
    if not isinstance(observations, list):
        raise ContractError("observations must be an array")

    _required_text(run.get("run_id"), "run.run_id")
    _required_text(run.get("collector"), "run.collector")
    _required_text(run.get("owner_sha"), "run.owner_sha")
    _timestamp(run.get("started_at"), "run.started_at")
    outcome = run.get("outcome")
    if not isinstance(outcome, str) or outcome not in OUTCOMES:
        raise ContractError(f"run.outcome must be one of {sorted(OUTCOMES)}")
    if not isinstance(run.get("scope_complete"), bool):
        raise ContractError("run.scope_complete must be a boolean")
    if outcome == "success":
        if run.get("scope_complete") is not True:
            raise ContractError("successful runs must prove the entire declared scope completed")
        _timestamp(run.get("completed_at"), "run.completed_at")
    elif run.get("scope_complete") is not False:
        raise ContractError("partial or failed runs cannot claim a complete scope")
    else:
        _timestamp(run.get("completed_at"), "run.completed_at")

    if not isinstance(run.get("scope"), str) or run.get("scope") not in SCOPES:
        raise ContractError(f"run.scope must be one of {sorted(SCOPES)}")
    for field in ("account_ref", "project_ref", "region_ref"):
        if field in run and not isinstance(run[field], str):
            raise ContractError(f"run.{field} must be a string when present")

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(observations):
        prefix = f"observations[{index}]"
        if not isinstance(item, Mapping):
            raise ContractError(f"{prefix} must be an object")
        for field in ("provider", "resource_kind", "native_resource_id", "provider_state", "source"):
            _required_text(item.get(field), f"{prefix}.{field}")
        if not isinstance(item.get("scope"), str) or item.get("scope") not in SCOPES:
            raise ContractError(f"{prefix}.scope must be one of {sorted(SCOPES)}")
        if not isinstance(item.get("source"), str) or item.get("source") not in SOURCES:
            raise ContractError(f"{prefix}.source must be one of {sorted(SOURCES)}")
        _timestamp(item.get("observed_at"), f"{prefix}.observed_at")
        attributes = item.get("attributes", {})
        if not isinstance(attributes, Mapping):
            raise ContractError(f"{prefix}.attributes must be an object")
        _reject_secret_keys(item, prefix)
        key = canonical_id(item)
        if key in seen:
            raise ContractError(f"duplicate canonical resource identity: {key}")
        seen.add(key)
        result = dict(item)
        result["canonical_id"] = key
        normalized.append(result)

    _reject_secret_keys(run, "run")
    return {
        "schema_version": SCHEMA_VERSION,
        "run": dict(run),
        "observations": normalized,
    }


def encode_envelope(document: Mapping[str, Any]) -> str:
    """Validate before producing deterministic JSON for a receipt/artifact."""
    normalized = validate_envelope(document)
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
