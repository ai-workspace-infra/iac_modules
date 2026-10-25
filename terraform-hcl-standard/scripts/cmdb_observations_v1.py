#!/usr/bin/env python3
"""Validate provider-neutral observed inventory envelopes before persistence.

Provider adapters must return a complete/partial run receipt and normalized
resource observations. This module deliberately performs no cloud API calls,
database writes, Terraform operations, or secret lookup.
"""

from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
import json
import re
from typing import Any, Iterable, Mapping
from urllib.parse import quote


SCHEMA_VERSION = "cmdb.observations.v1"
RECONCILIATION_SCHEMA_VERSION = "cmdb.reconciliation.v1"
SCOPES = {"dev", "shared", "sit", "uat", "prod", "unknown"}
SOURCES = {"provider_api", "external_inventory"}
OUTCOMES = {"success", "partial", "failed"}
RUNTIME_FORMS = {"vm", "k3s_node", "serverless"}
OBSERVATION_STATUSES = {"active", "unobserved", "collection_failed", "deleted"}
SERVERLESS_KINDS = {
    "serverless",
    "serverless_service",
    "serverless_revision",
    "serverless_worker",
    "serverless_pages",
    "cloud_run",
    "cloudflare_worker",
    "cloudflare_pages",
    "supabase",
    "managed_database",
}
COMPUTE_KINDS = {"compute", "vm", "k3s_node", "k3s", "k3s_server", "k3s_agent"}
K3S_INDICATORS = {"k3s_node", "k3s", "k3s_server", "k3s_agent", "k8s_cluster", "kubernetes"}
PROVIDER_ALIASES = {
    "gcp-cloud": "gcp",
    "aws-cloud": "aws",
    "vultr-vps": "vultr",
    "akamai-cloud": "akamai",
    "supabase-cloud": "supabase",
    "ali-cloud": "alicloud",
    "azure-cloud": "azure",
}
COMPUTE_URL_PREFIX = re.compile(r"^https?://(?:www\.|compute\.)?googleapis\.com/compute/v1/")
FAKE_ENDPOINT_OR_IP = re.compile(
    r"^(?:0\.0\.0\.0|127\.\d+\.\d+\.\d+|localhost|::1|none|null|n/a|"
    r"fake[-_.]?.*|dummy[-_.]?.*|placeholder[-_.]?.*|serverless[-_.]?host.*)$",
    re.IGNORECASE,
)
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


def _timestamp(value: Any, field: str) -> datetime:
    text = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{field} must include a timezone")
    return parsed


def normalize_provider(value: Any, field: str = "provider") -> str:
    raw = _required_text(value, field).lower()
    return PROVIDER_ALIASES.get(raw, raw)


def normalize_native_resource_id(value: Any, field: str = "native_resource_id") -> str:
    raw = _required_text(value, field)
    return COMPUTE_URL_PREFIX.sub("", raw).strip("/")


def _reject_secret_keys(value: Any, path: str = "observation") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if SECRET_KEY.search(str(key)):
                raise ContractError(f"secret-bearing field is not allowed: {path}.{key}")
            _reject_secret_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_keys(child, f"{path}[{index}]")


def classify_runtime_form(observation: Mapping[str, Any], prefix: str = "observation") -> str:
    """Classify observation runtime_form into 'vm', 'k3s_node', or 'serverless'."""
    provider = normalize_provider(observation.get("provider"), f"{prefix}.provider")
    kind = _required_text(observation.get("resource_kind"), f"{prefix}.resource_kind").lower()
    explicit_form = str(observation.get("runtime_form") or "").strip().lower()
    attrs = observation.get("attributes") if isinstance(observation.get("attributes"), Mapping) else {}
    groups = {str(g).strip().lower() for g in (observation.get("groups") or attrs.get("groups") or []) if g}

    is_serverless_kind = kind in SERVERLESS_KINDS or provider in {"cloudflare", "supabase"}
    is_k3s = (
        kind in {"k3s_node", "k3s", "k3s_server", "k3s_agent"}
        or bool(groups & K3S_INDICATORS)
        or str(attrs.get("deployment_mode") or "").strip().lower() == "kubernetes"
        or bool(str(attrs.get("k8s_cluster_name") or observation.get("cluster") or "").strip())
    )

    if explicit_form:
        if explicit_form not in RUNTIME_FORMS:
            raise ContractError(f"{prefix}.runtime_form must be one of {sorted(RUNTIME_FORMS)}")
        if explicit_form == "serverless" and kind in {"compute", "vm", "k3s_node"}:
            raise ContractError(f"{prefix}.runtime_form 'serverless' conflicts with resource_kind {kind!r}")
        if explicit_form in {"vm", "k3s_node"} and kind in SERVERLESS_KINDS:
            raise ContractError(f"{prefix}.runtime_form {explicit_form!r} conflicts with resource_kind {kind!r}")
        return explicit_form

    if is_serverless_kind:
        return "serverless"
    if is_k3s:
        return "k3s_node"
    return "vm"


def infer_observation_region(
    observation: Mapping[str, Any],
    *,
    run_region: str | None = None,
    prefix: str = "observation",
) -> str:
    """Resolve and validate region without silent cross-region misattribution."""
    attrs = observation.get("attributes") if isinstance(observation.get("attributes"), Mapping) else {}
    zone = str(observation.get("zone") or attrs.get("zone") or "").strip()
    zone_region = zone.rsplit("-", 1)[0] if "-" in zone and len(zone.split("-")) >= 3 else ""

    raw_region = observation.get("region")
    if raw_region is not None and (not isinstance(raw_region, str) or not raw_region.strip()):
        raise ContractError(f"{prefix}.region must be a non-empty string when present")
    explicit_region = raw_region.strip() if isinstance(raw_region, str) else ""

    if explicit_region and zone_region and explicit_region != zone_region:
        raise ContractError(
            f"{prefix}.region {explicit_region!r} conflicts with zone {zone!r} (expected {zone_region!r})"
        )

    resolved = explicit_region or zone_region
    if not resolved:
        clean_run_region = str(run_region or "").strip()
        if clean_run_region and clean_run_region not in {"all-zones", "multi-region"}:
            resolved = clean_run_region
        else:
            rform = classify_runtime_form(observation, prefix)
            provider = normalize_provider(observation.get("provider"), f"{prefix}.provider")
            if rform == "serverless" and provider in {"cloudflare"}:
                resolved = "global"

    if not resolved or resolved == "unknown":
        raise ContractError(f"{prefix}.region is required and cannot be unknown")

    clean_run_region = str(run_region or "").strip()
    if (
        clean_run_region
        and clean_run_region not in {"all-zones", "global", "multi-region"}
        and resolved != clean_run_region
    ):
        raise ContractError(
            f"{prefix}.region {resolved!r} conflicts with run.region_ref {clean_run_region!r}"
        )

    return resolved


def resource_key(observation: Mapping[str, Any], *, run_region: str | None = None) -> str:
    """Return authoritative resource_key: {provider}:{account_or_project}:{region}:{resource_id}."""
    provider = normalize_provider(observation.get("provider"), "provider")
    account_or_project = (
        str(observation.get("project_ref") or "").strip()
        or str(observation.get("account_ref") or "").strip()
        or "default"
    )
    region = infer_observation_region(observation, run_region=run_region)
    res_id = normalize_native_resource_id(observation.get("native_resource_id"), "native_resource_id")
    return f"{provider}:{account_or_project}:{region}:{res_id}"


def canonical_id(observation: Mapping[str, Any]) -> str:
    """Return a stable provider identity; names and IP addresses are excluded."""
    provider = normalize_provider(observation.get("provider"), "provider")
    project_ref = str(observation.get("project_ref", "")).strip()
    account_ref = str(observation.get("account_ref", "")).strip()
    raw_kind = _required_text(observation.get("resource_kind"), "resource_kind").lower()
    # Map equivalent compute kinds to canonical 'compute' and serverless service kinds consistently
    # so canonical_id does not split when runtime_form vs resource_kind is supplied.
    norm_kind = "compute" if raw_kind in {"vm", "k3s_node"} else (
        "serverless_service" if raw_kind == "serverless" else raw_kind
    )
    norm_id = normalize_native_resource_id(observation.get("native_resource_id"), "native_resource_id")
    parts = (
        provider,
        account_ref,
        project_ref,
        norm_kind,
        norm_id,
    )
    return "cmdb://" + "/".join(quote(part, safe="") or "_" for part in parts)


def _validate_endpoint_value(value: Any, field: str, *, require_ip: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ContractError(f"{field} must be a string or null")
    text = value.strip()
    if not text:
        return None
    if FAKE_ENDPOINT_OR_IP.match(text):
        raise ContractError(f"{field} cannot use fabricated or placeholder value {text!r}")
    if require_ip:
        try:
            ip_obj = ipaddress.ip_address(text)
            if ip_obj.is_unspecified or ip_obj.is_loopback:
                raise ContractError(f"{field} cannot use loopback or unspecified IP {text!r}")
        except ValueError as exc:
            if isinstance(exc, ContractError):
                raise
            raise ContractError(f"{field} must be a valid IP address, got {text!r}") from exc
    return text


def validate_envelope(document: Mapping[str, Any], *, deduplicate: bool = True) -> dict[str, Any]:
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

    run_scope = run.get("scope")
    if not isinstance(run_scope, str) or run_scope not in SCOPES:
        raise ContractError(f"run.scope must be one of {sorted(SCOPES)}")
    if "environment" in run and run["environment"] is not None:
        if not isinstance(run["environment"], str) or run["environment"] not in SCOPES:
            raise ContractError(f"run.environment must be one of {sorted(SCOPES)}")
        if run_scope != "unknown" and run["environment"] != "unknown" and run["environment"] != run_scope:
            raise ContractError(f"run.environment {run['environment']!r} conflicts with run.scope {run_scope!r}")

    for field in ("account_ref", "project_ref", "region_ref"):
        if field in run and not isinstance(run[field], str):
            raise ContractError(f"run.{field} must be a string when present")

    run_project = str(run.get("project_ref") or "").strip()
    run_region = str(run.get("region_ref") or "").strip()

    by_resource_key: dict[str, int] = {}
    seen_canonical: set[str] = set()
    normalized: list[dict[str, Any]] = []

    for index, item in enumerate(observations):
        prefix = f"observations[{index}]"
        if not isinstance(item, Mapping):
            raise ContractError(f"{prefix} must be an object")
        for field in ("provider", "resource_kind", "native_resource_id", "provider_state", "source"):
            _required_text(item.get(field), f"{prefix}.{field}")

        item_scope = item.get("scope")
        if not isinstance(item_scope, str) or item_scope not in SCOPES:
            raise ContractError(f"{prefix}.scope must be one of {sorted(SCOPES)}")
        if run_scope != "unknown" and item_scope != run_scope:
            raise ContractError(
                f"{prefix}.scope {item_scope!r} conflicts with run.scope {run_scope!r}"
            )

        item_env = item.get("environment")
        if item_env is not None:
            if not isinstance(item_env, str) or item_env not in SCOPES:
                raise ContractError(f"{prefix}.environment must be one of {sorted(SCOPES)}")
            if item_env != item_scope:
                raise ContractError(
                    f"{prefix}.environment {item_env!r} conflicts with {prefix}.scope {item_scope!r}"
                )
        resolved_env = item_env or item_scope

        item_project = str(item.get("project_ref") or "").strip()
        if run_project and item_project and item_project != run_project:
            raise ContractError(
                f"{prefix}.project_ref {item_project!r} conflicts with run.project_ref {run_project!r}"
            )

        if not isinstance(item.get("source"), str) or item.get("source") not in SOURCES:
            raise ContractError(f"{prefix}.source must be one of {sorted(SOURCES)}")

        obs_dt = _timestamp(item.get("observed_at"), f"{prefix}.observed_at")
        last_obs_raw = item.get("last_observed_at") or item.get("observed_at")
        last_obs_dt = _timestamp(last_obs_raw, f"{prefix}.last_observed_at")
        if last_obs_dt < obs_dt:
            last_obs_raw = item.get("observed_at")
            last_obs_dt = obs_dt

        attributes = item.get("attributes", {})
        if not isinstance(attributes, Mapping):
            raise ContractError(f"{prefix}.attributes must be an object")
        _reject_secret_keys(item, prefix)

        rform = classify_runtime_form(item, prefix)
        resolved_region = infer_observation_region(item, run_region=run_region, prefix=prefix)

        pub_ep = _validate_endpoint_value(item.get("public_endpoint"), f"{prefix}.public_endpoint")
        priv_ep = _validate_endpoint_value(item.get("private_endpoint"), f"{prefix}.private_endpoint")
        raw_ssh = item.get("ssh_host")
        raw_pip = item.get("primary_ip")

        if rform == "serverless":
            if raw_ssh not in (None, ""):
                raise ContractError(f"{prefix} is serverless and cannot have ssh_host {raw_ssh!r}")
            if raw_pip not in (None, ""):
                raise ContractError(f"{prefix} is serverless and cannot have primary_ip {raw_pip!r}")
            if priv_ep is not None and item.get("resource_kind") != "managed_database":
                raise ContractError(f"{prefix} is serverless and cannot have private_endpoint {priv_ep!r}")
            ssh_host = None
            primary_ip = None
        else:
            primary_ip = _validate_endpoint_value(
                raw_pip if raw_pip not in (None, "") else (pub_ep or priv_ep),
                f"{prefix}.primary_ip",
                require_ip=True,
            )
            ssh_host = _validate_endpoint_value(
                raw_ssh if raw_ssh not in (None, "") else (pub_ep or priv_ep),
                f"{prefix}.ssh_host",
                require_ip=False,
            )

        normalized_item = dict(item)
        normalized_item["provider"] = normalize_provider(item.get("provider"), f"{prefix}.provider")
        normalized_item["native_resource_id"] = normalize_native_resource_id(
            item.get("native_resource_id"), f"{prefix}.native_resource_id"
        )
        if not normalized_item.get("project_ref") and run_project:
            normalized_item["project_ref"] = run_project
        if not normalized_item.get("account_ref"):
            normalized_item["account_ref"] = (
                str(normalized_item.get("project_ref") or run.get("account_ref") or "").strip()
            )
        normalized_item["region"] = resolved_region
        normalized_item["environment"] = resolved_env
        normalized_item["runtime_form"] = rform
        normalized_item["ssh_host"] = ssh_host
        normalized_item["primary_ip"] = primary_ip
        normalized_item["last_observed_at"] = str(last_obs_raw).strip()
        normalized_item["service"] = str(
            item.get("service")
            or attributes.get("service")
            or attributes.get("service_name")
            or item.get("name")
            or ""
        ).strip()
        normalized_item["cluster"] = str(
            item.get("cluster")
            or attributes.get("cluster")
            or attributes.get("k8s_cluster_name")
            or ""
        ).strip()
        normalized_item["namespace"] = str(
            item.get("namespace")
            or attributes.get("namespace")
            or attributes.get("k8s_namespace")
            or ""
        ).strip()
        normalized_item["node"] = str(
            item.get("node")
            or attributes.get("node")
            or (item.get("name") or "" if rform in {"vm", "k3s_node"} else "")
        ).strip()
        normalized_item["observation_status"] = "active" if outcome == "success" else "collection_failed"

        rkey = resource_key(normalized_item, run_region=run_region)
        cid = canonical_id(normalized_item)
        normalized_item["resource_key"] = rkey
        normalized_item["canonical_id"] = cid

        if rkey in by_resource_key:
            if not deduplicate:
                raise ContractError(f"duplicate canonical resource identity: {rkey}")
            prev_idx = by_resource_key[rkey]
            prev = normalized[prev_idx]
            if prev["scope"] != normalized_item["scope"] or prev["runtime_form"] != normalized_item["runtime_form"]:
                raise ContractError(
                    f"conflicting duplicate observation for {rkey}: "
                    f"({prev['scope']}, {prev['runtime_form']}) vs "
                    f"({normalized_item['scope']}, {normalized_item['runtime_form']})"
                )
            prev_dt = _timestamp(prev["last_observed_at"], "last_observed_at")
            if last_obs_dt >= prev_dt:
                merged_attrs = dict(prev.get("attributes") or {})
                merged_attrs.update(attributes)
                normalized_item["attributes"] = merged_attrs
                normalized[prev_idx] = normalized_item
            continue

        if cid in seen_canonical and not deduplicate:
            raise ContractError(f"duplicate canonical resource identity: {cid}")

        seen_canonical.add(cid)
        by_resource_key[rkey] = len(normalized)
        normalized.append(normalized_item)

    _reject_secret_keys(run, "run")
    return {
        "schema_version": SCHEMA_VERSION,
        "run": dict(run),
        "observations": normalized,
    }


def deduplicate_observations(observations: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Idempotently deduplicate observations across pages or sources by authoritative resource_key."""
    by_key: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(observations):
        prefix = f"observations[{index}]"
        rform = classify_runtime_form(item, prefix)
        reg = infer_observation_region(item, prefix=prefix)
        copy_item = dict(item)
        copy_item["provider"] = normalize_provider(item.get("provider"), f"{prefix}.provider")
        copy_item["native_resource_id"] = normalize_native_resource_id(
            item.get("native_resource_id"), f"{prefix}.native_resource_id"
        )
        copy_item["region"] = reg
        copy_item["runtime_form"] = rform
        rkey = resource_key(copy_item)
        copy_item["resource_key"] = rkey
        copy_item["canonical_id"] = canonical_id(copy_item)
        obs_ts = str(copy_item.get("last_observed_at") or copy_item.get("observed_at") or "").strip()
        new_dt = _timestamp(obs_ts, f"{prefix}.observed_at")
        copy_item["last_observed_at"] = obs_ts

        existing = by_key.get(rkey)
        if existing is not None:
            existing_scope = existing.get("environment") or existing.get("scope")
            new_scope = copy_item.get("environment") or copy_item.get("scope")
            if existing_scope and new_scope and existing_scope != new_scope:
                raise ContractError(
                    f"cross-environment duplicate resource_key {rkey}: {existing_scope!r} vs {new_scope!r}"
                )
            old_dt = _timestamp(existing["last_observed_at"], "last_observed_at")
            if new_dt < old_dt:
                continue
        by_key[rkey] = copy_item
    return list(by_key.values())


def _normalize_desired_entry(item: Mapping[str, Any], index: int) -> dict[str, Any]:
    prefix = f"desired_resources[{index}]"
    provider = normalize_provider(
        item.get("provider") or item.get("cloud_provider"), f"{prefix}.provider"
    )
    scope = str(item.get("environment") or item.get("scope") or "unknown").strip().lower()
    if scope not in SCOPES:
        raise ContractError(f"{prefix}.environment must be one of {sorted(SCOPES)}")
    project_ref = str(
        item.get("project_ref") or item.get("project_id") or item.get("account_ref") or item.get("account") or ""
    ).strip()
    account_ref = str(item.get("account_ref") or item.get("account") or project_ref).strip()
    raw_kind = str(item.get("resource_kind") or item.get("runtime_form") or "compute").strip().lower()
    res_id = normalize_native_resource_id(
        item.get("native_resource_id") or item.get("resource_id") or item.get("instance_id") or item.get("name"),
        f"{prefix}.resource_id",
    )
    temp = {
        "provider": provider,
        "account_ref": account_ref,
        "project_ref": project_ref,
        "resource_kind": raw_kind,
        "runtime_form": item.get("runtime_form"),
        "native_resource_id": res_id,
        "region": item.get("region") or item.get("cloud_region"),
        "zone": item.get("zone"),
        "scope": scope,
        "environment": scope,
        "name": str(item.get("name") or res_id),
        "groups": item.get("groups") or [],
        "attributes": item.get("attributes") if isinstance(item.get("attributes"), Mapping) else {},
    }
    rform = classify_runtime_form(temp, prefix)
    region = infer_observation_region(temp, prefix=prefix)
    temp["region"] = region
    temp["runtime_form"] = rform
    temp["resource_kind"] = (
        "serverless_service"
        if rform == "serverless" and raw_kind == "serverless"
        else ("compute" if rform in {"vm", "k3s_node"} and raw_kind in {"vm", "k3s_node"} else raw_kind)
    )
    rkey = resource_key(temp)
    cid = canonical_id(temp)
    return {
        "resource_key": rkey,
        "canonical_id": cid,
        "provider": provider,
        "account_ref": account_ref,
        "project_ref": project_ref,
        "region": region,
        "scope": scope,
        "environment": scope,
        "resource_kind": temp["resource_kind"],
        "runtime_form": rform,
        "native_resource_id": res_id,
        "name": temp["name"],
        "ssh_host": None if rform == "serverless" else item.get("ssh_host") or item.get("ip"),
        "primary_ip": None if rform == "serverless" else item.get("primary_ip") or item.get("ip"),
        "service": str(item.get("service") or temp["name"]).strip(),
        "cluster": str(item.get("cluster") or "").strip(),
        "namespace": str(item.get("namespace") or "").strip(),
        "node": str(item.get("node") or (temp["name"] if rform in {"vm", "k3s_node"} else "")).strip(),
    }


def _matches_run_scope(resource: Mapping[str, Any], run: Mapping[str, Any]) -> bool:
    collector = str(run.get("collector") or "").strip().lower()
    run_provider = str(run.get("provider") or (collector.split("-", 1)[0] if "-" in collector else "")).strip().lower()
    if run_provider and normalize_provider(resource.get("provider", "unknown")) != normalize_provider(run_provider):
        return False

    run_scope = str(run.get("scope") or "").strip().lower()
    res_scope = str(resource.get("scope") or resource.get("environment") or "").strip().lower()
    if run_scope and run_scope != "unknown" and res_scope != run_scope:
        return False

    run_project = str(run.get("project_ref") or run.get("account_ref") or "").strip()
    res_project = str(resource.get("project_ref") or resource.get("account_ref") or "").strip()
    if run_project and res_project and run_project != res_project:
        return False

    run_kind = str(run.get("resource_kind") or "").strip().lower()
    if not run_kind and "-" in collector:
        suffix = collector.split("-", 1)[1]
        run_kind = "compute" if suffix == "compute" else ("serverless_service" if suffix == "cloudrun" else suffix)
    res_kind = str(resource.get("resource_kind") or "").strip().lower()
    res_form = str(resource.get("runtime_form") or "").strip().lower()
    if run_kind:
        if run_kind in COMPUTE_KINDS and res_kind not in COMPUTE_KINDS and res_form not in {"vm", "k3s_node"}:
            return False
        if run_kind in SERVERLESS_KINDS and res_kind not in SERVERLESS_KINDS and res_form != "serverless":
            return False
        if run_kind not in COMPUTE_KINDS and run_kind not in SERVERLESS_KINDS and res_kind != run_kind:
            return False

    run_region = str(run.get("region_ref") or "").strip()
    res_region = str(resource.get("region") or "").strip()
    if run_region and run_region not in {"all-zones", "global", "multi-region"} and res_region != run_region:
        return False

    return True


def reconcile_observations(
    envelopes: Iterable[Mapping[str, Any]],
    *,
    desired_resources: Iterable[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]] | None = None,
    prior_resources: Iterable[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Reconcile desired declarations, prior CMDB state, and observed run envelopes.

    Guarantees:
    - Idempotent deduplication by authoritative resource_key ({provider}:{account_or_project}:{region}:{resource_id}).
    - Preserves observed_at and last_observed_at across replays and partial failures.
    - Distinguishes 'active', 'unobserved', 'collection_failed', and 'deleted'.
    - Partial/failed runs NEVER mark existing active resources in that scope as 'deleted'.
    - Complete runs ('outcome' == 'success' and 'scope_complete' == True) transition missing
      prior resources in that scope to 'deleted' ('lifecycle' = 'deletion_confirmed').
    - Authoritative active counts include only currently valid ('lifecycle' == 'present') resources.
    """
    desired_by_key: dict[str, dict[str, Any]] = {}
    if desired_resources is not None:
        raw_desired = (
            list(desired_resources.values())
            if isinstance(desired_resources, Mapping)
            else list(desired_resources)
        )
        for idx, item in enumerate(raw_desired):
            norm_des = _normalize_desired_entry(item, idx)
            rkey = norm_des["resource_key"]
            if rkey in desired_by_key and desired_by_key[rkey]["environment"] != norm_des["environment"]:
                raise ContractError(f"conflicting desired environment for {rkey}")
            desired_by_key[rkey] = norm_des

    state_by_key: dict[str, dict[str, Any]] = {}
    if prior_resources is not None:
        raw_prior = (
            list(prior_resources.values())
            if isinstance(prior_resources, Mapping)
            else list(prior_resources)
        )
        for item in raw_prior:
            copy_item = dict(item)
            rkey = str(copy_item.get("resource_key") or "") or resource_key(copy_item)
            copy_item["resource_key"] = rkey
            copy_item.setdefault("canonical_id", canonical_id(copy_item))
            copy_item.setdefault("runtime_form", classify_runtime_form(copy_item))
            copy_item.setdefault("environment", copy_item.get("scope", "unknown"))
            copy_item.setdefault("scope", copy_item.get("environment", "unknown"))
            obs_ts = copy_item.get("last_observed_at") or copy_item.get("observed_at")
            copy_item["observed_at"] = copy_item.get("observed_at") or obs_ts
            copy_item["last_observed_at"] = obs_ts
            status = str(copy_item.get("status") or copy_item.get("observation_status") or "active")
            copy_item["status"] = status
            copy_item["observation_status"] = status
            if "lifecycle" not in copy_item:
                copy_item["lifecycle"] = (
                    "deletion_confirmed"
                    if status == "deleted"
                    else ("never_observed" if status == "unobserved" else "present")
                )
            state_by_key[rkey] = copy_item

    for rkey, des in desired_by_key.items():
        if rkey not in state_by_key:
            state_by_key[rkey] = {
                **des,
                "status": "unobserved",
                "observation_status": "unobserved",
                "lifecycle": "never_observed",
                "observed_at": None,
                "last_observed_at": None,
                "provider_state": "unobserved",
                "observed_match": "declared_only",
            }

    validated_envelopes = [validate_envelope(env, deduplicate=True) for env in envelopes]
    validated_envelopes.sort(key=lambda e: _timestamp(e["run"]["completed_at"], "run.completed_at"))

    latest_run_ts: str | None = None
    run_summaries: list[dict[str, Any]] = []

    for env in validated_envelopes:
        run = env["run"]
        outcome = run["outcome"]
        scope_complete = run["scope_complete"]
        completed_dt = _timestamp(run["completed_at"], "run.completed_at")
        latest_run_ts = run["completed_at"]
        seen_in_run: set[str] = set()

        for obs in env["observations"]:
            rkey = obs["resource_key"]
            seen_in_run.add(rkey)
            obs_dt = _timestamp(obs["last_observed_at"], "last_observed_at")
            existing = state_by_key.get(rkey)

            if existing is not None:
                existing_env = existing.get("environment") or existing.get("scope")
                if existing_env and existing_env != "unknown" and obs["environment"] != existing_env:
                    raise ContractError(
                        f"cross-environment observation for {rkey}: "
                        f"existing {existing_env!r} vs observed {obs['environment']!r}"
                    )
                prev_ts = existing.get("last_observed_at")
                if prev_ts:
                    prev_dt = _timestamp(prev_ts, "last_observed_at")
                    if obs_dt < prev_dt:
                        continue

            status = "active" if outcome == "success" else "collection_failed"
            record = {
                **(existing or {}),
                **obs,
                "resource_key": rkey,
                "canonical_id": obs["canonical_id"],
                "environment": obs["environment"],
                "scope": obs["scope"],
                "runtime_form": obs["runtime_form"],
                "ssh_host": obs["ssh_host"],
                "primary_ip": obs["primary_ip"],
                "observed_at": obs["observed_at"],
                "last_observed_at": obs["last_observed_at"],
                "status": status,
                "observation_status": status,
                "lifecycle": "present",
                "last_run_id": run["run_id"],
            }
            record.pop("deleted_at", None)
            if outcome == "success":
                record.pop("last_collection_error", None)
            else:
                record["last_collection_error"] = run.get("error_class") or outcome
            state_by_key[rkey] = record

        for rkey, current in list(state_by_key.items()):
            if rkey in seen_in_run or not _matches_run_scope(current, run):
                continue
            prev_ts = current.get("last_observed_at")
            if prev_ts and _timestamp(prev_ts, "last_observed_at") > completed_dt:
                continue

            if outcome == "success" and scope_complete is True:
                if current.get("lifecycle") == "present" or prev_ts is not None:
                    current["status"] = "deleted"
                    current["observation_status"] = "deleted"
                    current["lifecycle"] = "deletion_confirmed"
                    current["provider_state"] = "deleted"
                    current["deleted_at"] = run["completed_at"]
                    current["last_run_id"] = run["run_id"]
                else:
                    current["status"] = "unobserved"
                    current["observation_status"] = "unobserved"
                    current["lifecycle"] = "never_observed"
            else:
                # Partial or failed API collection: NEVER mark existing assets as deleted!
                current["status"] = "collection_failed"
                current["observation_status"] = "collection_failed"
                if prev_ts is not None or current.get("lifecycle") == "present":
                    current["lifecycle"] = "present"
                current["last_collection_error"] = run.get("error_class") or outcome
                current["last_run_id"] = run["run_id"]

        run_summaries.append(
            {
                "run_id": run["run_id"],
                "collector": run["collector"],
                "scope": run["scope"],
                "project_ref": run.get("project_ref", ""),
                "region_ref": run.get("region_ref", ""),
                "outcome": outcome,
                "scope_complete": scope_complete,
                "resources_seen": len(seen_in_run),
                "completed_at": run["completed_at"],
                "error_class": run.get("error_class"),
            }
        )

    diffs: list[dict[str, Any]] = []
    by_env: dict[str, dict[str, int]] = {}
    by_form: dict[str, dict[str, int]] = {
        form: {"declared_count": 0, "active_count": 0, "deleted_count": 0, "unobserved_count": 0, "collection_failed_count": 0}
        for form in sorted(RUNTIME_FORMS)
    }

    for rkey, des in desired_by_key.items():
        env_name = des["environment"]
        by_env.setdefault(
            env_name,
            {
                "declared_count": 0,
                "active_count": 0,
                "vm_count": 0,
                "k3s_node_count": 0,
                "serverless_count": 0,
                "unobserved_count": 0,
                "collection_failed_count": 0,
                "deleted_count": 0,
            },
        )["declared_count"] += 1
        by_form[des["runtime_form"]]["declared_count"] += 1

    matched_count = 0
    declared_only_count = 0
    observed_only_count = 0
    drifted_count = 0
    active_count = 0
    observed_active_count = 0
    unobserved_count = 0
    collection_failed_count = 0
    deleted_count = 0

    for rkey in sorted(state_by_key):
        rec = state_by_key[rkey]
        env_name = str(rec.get("environment") or rec.get("scope") or "unknown")
        rform = str(rec.get("runtime_form") or "vm")
        status = rec["status"]
        lifecycle = rec["lifecycle"]

        env_bucket = by_env.setdefault(
            env_name,
            {
                "declared_count": 0,
                "active_count": 0,
                "vm_count": 0,
                "k3s_node_count": 0,
                "serverless_count": 0,
                "unobserved_count": 0,
                "collection_failed_count": 0,
                "deleted_count": 0,
            },
        )
        form_bucket = by_form.setdefault(
            rform,
            {"declared_count": 0, "active_count": 0, "deleted_count": 0, "unobserved_count": 0, "collection_failed_count": 0},
        )

        if lifecycle == "present":
            active_count += 1
            env_bucket["active_count"] += 1
            env_bucket[f"{rform}_count"] = env_bucket.get(f"{rform}_count", 0) + 1
            form_bucket["active_count"] += 1

        if status == "active":
            observed_active_count += 1
        elif status == "unobserved":
            unobserved_count += 1
            env_bucket["unobserved_count"] += 1
            form_bucket["unobserved_count"] += 1
        elif status == "collection_failed":
            collection_failed_count += 1
            env_bucket["collection_failed_count"] += 1
            form_bucket["collection_failed_count"] += 1
        elif status == "deleted":
            deleted_count += 1
            env_bucket["deleted_count"] += 1
            form_bucket["deleted_count"] += 1

        des = desired_by_key.get(rkey)
        if des is not None:
            if lifecycle == "present":
                if des["region"] != rec["region"] or des["runtime_form"] != rec["runtime_form"]:
                    rec["observed_match"] = "drifted"
                    drifted_count += 1
                    diffs.append(
                        {
                            "resource_key": rkey,
                            "environment": env_name,
                            "runtime_form": rform,
                            "status": status,
                            "observed_match": "drifted",
                            "last_observed_at": rec.get("last_observed_at"),
                            "detail": "region or runtime_form drifted from desired declaration",
                        }
                    )
                else:
                    rec["observed_match"] = "matched"
                    matched_count += 1
                    if status == "collection_failed":
                        diffs.append(
                            {
                                "resource_key": rkey,
                                "environment": env_name,
                                "runtime_form": rform,
                                "status": status,
                                "observed_match": "matched",
                                "last_observed_at": rec.get("last_observed_at"),
                                "detail": f"retained active asset during partial/failed collection ({rec.get('last_collection_error')})",
                            }
                        )
            else:
                rec["observed_match"] = "declared_only"
                declared_only_count += 1
                diffs.append(
                    {
                        "resource_key": rkey,
                        "environment": env_name,
                        "runtime_form": rform,
                        "status": status,
                        "observed_match": "declared_only",
                        "last_observed_at": rec.get("last_observed_at"),
                        "detail": "declared resource was confirmed deleted" if status == "deleted" else "declared resource has not been observed",
                    }
                )
        else:
            if lifecycle == "present":
                rec["observed_match"] = "observed_only"
                observed_only_count += 1
                diffs.append(
                    {
                        "resource_key": rkey,
                        "environment": env_name,
                        "runtime_form": rform,
                        "status": status,
                        "observed_match": "observed_only",
                        "last_observed_at": rec.get("last_observed_at"),
                        "detail": "observed active resource is not in desired declarations",
                    }
                )
            else:
                rec["observed_match"] = "deleted"
                diffs.append(
                    {
                        "resource_key": rkey,
                        "environment": env_name,
                        "runtime_form": rform,
                        "status": status,
                        "observed_match": "deleted",
                        "last_observed_at": rec.get("last_observed_at"),
                        "detail": "previously observed resource was confirmed deleted in complete scope run",
                    }
                )

    report_ts = str(generated_at or latest_run_ts or datetime.now(timezone.utc).isoformat()).strip()
    _timestamp(report_ts, "generated_at")

    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "generated_at": report_ts,
        "summary": {
            "declared_count": len(desired_by_key),
            "active_count": active_count,
            "observed_active_count": observed_active_count,
            "unobserved_count": unobserved_count,
            "collection_failed_count": collection_failed_count,
            "deleted_count": deleted_count,
            "matched_count": matched_count,
            "declared_only_count": declared_only_count,
            "observed_only_count": observed_only_count,
            "drifted_count": drifted_count,
        },
        "by_environment": by_env,
        "by_runtime_form": by_form,
        "runs": run_summaries,
        "diffs": diffs,
        "resources": {k: state_by_key[k] for k in sorted(state_by_key)},
    }


def encode_envelope(document: Mapping[str, Any]) -> str:
    """Validate before producing deterministic JSON for a receipt/artifact."""
    normalized = validate_envelope(document)
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
