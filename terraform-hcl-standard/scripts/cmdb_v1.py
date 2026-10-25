#!/usr/bin/env python3
"""Small shared writer for the IaC -> Playbooks CMDB contract.

The top-level host keys are intentionally retained for older callers that use
``jq '.<host>.ip'``. New consumers should read ``hosts`` and validate
``schema_version`` first.
"""

from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "cmdb.v1"
SUPPORTED_ENVIRONMENTS = {"dev", "sit", "uat", "prod", "shared"}
RUNTIME_FORMS = {"vm", "k3s_node", "serverless"}
LIFECYCLE_STATES = {"active", "unobserved", "collection_failed", "deleted"}
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
K3S_GROUPS = {"k3s_server", "k3s_agent", "k3s_node", "k3s", "k8s_cluster"}
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
FAKE_HOST_OR_IP = re.compile(
    r"^(?:0\.0\.0\.0|127\.\d+\.\d+\.\d+|localhost|::1|none|null|n/a|unknown|"
    r"fake[-_.]?.*|dummy[-_.]?.*|placeholder[-_.]?.*|serverless[-_.]?host.*)$",
    re.IGNORECASE,
)
SECRET_KEY = re.compile(r"(?:password|token|secret|private[_-]?key|credential)", re.IGNORECASE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: Any, field: str = "observed_at") -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def normalize_provider(provider: Any) -> str:
    text = str(provider or "").strip().lower()
    if not text:
        raise ValueError("provider must be a non-empty string")
    return PROVIDER_ALIASES.get(text, text)


def normalize_native_resource_id(resource_id: Any, fallback: str = "") -> str:
    raw = str(resource_id if resource_id is not None else "").strip()
    if not raw:
        raw = str(fallback or "").strip()
    if not raw:
        raise ValueError("resource_id must be a non-empty string")
    return COMPUTE_URL_PREFIX.sub("", raw).strip("/")


def build_resource_key(
    provider: Any,
    account_or_project: Any,
    region: Any,
    resource_id: Any,
) -> str:
    """Build the authoritative resource_key: {provider}:{account_or_project}:{region}:{resource_id}."""
    norm_provider = normalize_provider(provider)
    acct_proj = str(account_or_project or "").strip() or "default"
    reg = str(region or "").strip() or "unknown"
    norm_id = normalize_native_resource_id(resource_id)
    return f"{norm_provider}:{acct_proj}:{reg}:{norm_id}"


def _extract_path_environments(resource_paths: str | list[str]) -> set[str]:
    paths = resource_paths if isinstance(resource_paths, list) else str(resource_paths or "").split(",")
    found: set[str] = set()
    for raw_path in paths:
        cleaned = raw_path.strip()
        if not cleaned:
            continue
        path_obj = Path(cleaned)
        matched_in_path: set[str] = set()
        for part in path_obj.parts[:-1]:
            if part in SUPPORTED_ENVIRONMENTS:
                matched_in_path.add(part)
        if not matched_in_path:
            stem_tokens = [tok for tok in re.split(r"[^a-z0-9]+", path_obj.stem.lower()) if tok]
            for tok in stem_tokens:
                if tok in SUPPORTED_ENVIRONMENTS:
                    matched_in_path.add(tok)
        found.update(matched_in_path)
    return found


def infer_environment(resource_paths: str | list[str], explicit: str | None = None) -> str:
    """Resolve the environment from an explicit value or a GitOps path without cross-env fallback."""
    path_envs = _extract_path_environments(resource_paths)
    if len(path_envs) > 1:
        raise ValueError(
            f"resource_paths span multiple environments {sorted(path_envs)}; "
            "cross-environment CMDB generation is prohibited"
        )
    path_env = next(iter(path_envs), None)

    if explicit is not None and str(explicit).strip():
        candidate = str(explicit).strip().lower()
        if candidate not in SUPPORTED_ENVIRONMENTS and candidate != "unknown":
            raise ValueError(f"unsupported environment {explicit!r}; must be one of {sorted(SUPPORTED_ENVIRONMENTS)}")
        if path_env and candidate != "unknown" and candidate != path_env:
            raise ValueError(
                f"explicit environment {candidate!r} conflicts with resource path environment {path_env!r}"
            )
        return candidate

    env_var = os.environ.get("DEPLOY_ENVIRONMENT", "").strip().lower()
    if path_env:
        if env_var and env_var in SUPPORTED_ENVIRONMENTS and env_var != path_env:
            raise ValueError(
                f"DEPLOY_ENVIRONMENT {env_var!r} conflicts with resource path environment {path_env!r}"
            )
        return path_env

    if env_var in SUPPORTED_ENVIRONMENTS:
        return env_var
    return "unknown"


def classify_runtime_form(record: Mapping[str, Any], cloud_provider: str = "") -> str:
    """Classify a resource into 'vm', 'k3s_node', or 'serverless'."""
    explicit_form = str(record.get("runtime_form") or "").strip().lower()
    kind = str(record.get("resource_kind") or "").strip().lower()
    norm_provider = normalize_provider(
        record.get("provider") or record.get("cloud_provider") or cloud_provider or "unknown"
    )
    host_vars = record.get("host_vars") if isinstance(record.get("host_vars"), Mapping) else {}
    groups = {str(g).strip().lower() for g in (record.get("groups") or []) if g}

    is_serverless_kind = kind in SERVERLESS_KINDS or norm_provider in {"cloudflare", "supabase"}
    is_k3s = (
        kind in {"k3s_node", "k3s", "k3s_server", "k3s_agent"}
        or bool(groups & K3S_GROUPS)
        or str(host_vars.get("deployment_mode") or "").strip().lower() == "kubernetes"
        or bool(str(host_vars.get("k8s_cluster_name") or "").strip())
    )

    if explicit_form:
        if explicit_form not in RUNTIME_FORMS:
            raise ValueError(f"runtime_form must be one of {sorted(RUNTIME_FORMS)}, got {explicit_form!r}")
        if explicit_form == "serverless" and kind in {"vm", "compute", "k3s_node"}:
            raise ValueError(f"runtime_form 'serverless' conflicts with resource_kind {kind!r}")
        if explicit_form in {"vm", "k3s_node"} and kind in SERVERLESS_KINDS:
            raise ValueError(f"runtime_form {explicit_form!r} conflicts with serverless resource_kind {kind!r}")
        return explicit_form

    if is_serverless_kind:
        return "serverless"
    if is_k3s:
        return "k3s_node"
    return "vm"


def infer_region(
    record: Mapping[str, Any],
    default_region: str | None = None,
    *,
    runtime_form: str = "vm",
    cloud_provider: str = "",
) -> str:
    """Resolve region from record/zone without silently misattributing cross-region zones."""
    host_vars = record.get("host_vars") if isinstance(record.get("host_vars"), Mapping) else {}
    attrs = record.get("attributes") if isinstance(record.get("attributes"), Mapping) else {}
    zone = str(record.get("zone") or attrs.get("zone") or "").strip()
    zone_region = zone.rsplit("-", 1)[0] if "-" in zone and len(zone.split("-")) >= 3 else ""

    explicit_region = str(record.get("region") or "").strip()
    provider_region = str(
        host_vars.get("provider_region")
        or record.get("cloud_region")
        or host_vars.get("cloud_region")
        or ""
    ).strip()

    if explicit_region and zone_region and explicit_region != zone_region:
        raise ValueError(f"resource region {explicit_region!r} conflicts with zone {zone!r}")

    if zone_region:
        return zone_region
    if explicit_region:
        return explicit_region
    if provider_region:
        return provider_region
    if default_region and str(default_region).strip():
        return str(default_region).strip()

    norm_provider = normalize_provider(
        record.get("provider") or record.get("cloud_provider") or cloud_provider or "unknown"
    )
    if runtime_form == "serverless" and norm_provider in {"cloudflare"}:
        return "global"
    return "unknown"


def _validate_endpoint_or_ip(value: Any, *, field: str, allow_hostname: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if FAKE_HOST_OR_IP.match(text):
        raise ValueError(f"fabricated or placeholder {field} is not allowed: {text!r}")
    if not allow_hostname:
        try:
            ip_obj = ipaddress.ip_address(text)
            if ip_obj.is_unspecified or ip_obj.is_loopback:
                raise ValueError(f"loopback or unspecified {field} is not allowed: {text!r}")
        except ValueError as exc:
            if "not allowed" in str(exc):
                raise
            raise ValueError(f"{field} must be a valid IP address, got {text!r}") from exc
    return text


def normalize_resource_record(
    name: str,
    record: Mapping[str, Any],
    *,
    cloud_provider: str,
    environment: str,
    project_id: str | None = None,
    default_region: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Normalize a host or serverless resource into the unified CMDB resource contract."""
    if not isinstance(record, Mapping):
        raise ValueError(f"CMDB resource {name!r} must be an object")

    host_vars = record.get("host_vars") if isinstance(record.get("host_vars"), Mapping) else {}
    for key in host_vars:
        if SECRET_KEY.search(str(key)):
            raise ValueError(
                f"CMDB host {name} contains secret-like host_vars key {key!r}; "
                "runtime credentials must stay outside the CMDB"
            )

    rec_env = str(record.get("environment") or record.get("scope") or "").strip().lower()
    if rec_env and environment != "unknown" and rec_env != "unknown" and rec_env != environment:
        raise ValueError(
            f"resource {name!r} environment {rec_env!r} conflicts with document environment {environment!r}"
        )
    resolved_env = rec_env or environment

    provider = normalize_provider(record.get("provider") or record.get("cloud_provider") or cloud_provider)
    rform = classify_runtime_form(record, cloud_provider=provider)
    region = infer_region(record, default_region, runtime_form=rform, cloud_provider=provider)

    acct_proj = (
        str(
            record.get("project_id")
            or record.get("project_ref")
            or record.get("account_ref")
            or record.get("account")
            or project_id
            or resolved_env
            or "default"
        ).strip()
    )
    raw_res_id = (
        record.get("resource_id")
        or record.get("native_resource_id")
        or record.get("instance_id")
        or record.get("id")
        or record.get("name")
        or name
    )
    res_id = normalize_native_resource_id(raw_res_id, fallback=name)
    rkey = build_resource_key(provider, acct_proj, region, res_id)

    raw_ip = record.get("primary_ip") if "primary_ip" in record else record.get("ip")
    raw_private_ip = record.get("private_ip")
    raw_ssh_host = record.get("ssh_host") if "ssh_host" in record else record.get("ansible_host")

    if rform == "serverless":
        if raw_ip not in (None, "") or raw_private_ip not in (None, "") or raw_ssh_host not in (None, ""):
            raise ValueError(
                f"serverless resource {name!r} cannot define primary_ip/ip or ssh_host/ansible_host"
            )
        primary_ip = None
        ssh_host = None
        resource_kind = str(record.get("resource_kind") or "serverless_service").strip()
    else:
        primary_ip = _validate_endpoint_or_ip(
            raw_ip if raw_ip not in (None, "") else raw_private_ip,
            field=f"{name}.primary_ip",
            allow_hostname=False,
        )
        ssh_candidate = raw_ssh_host if raw_ssh_host not in (None, "") else (raw_ip or raw_private_ip)
        ssh_host = _validate_endpoint_or_ip(
            ssh_candidate,
            field=f"{name}.ssh_host",
            allow_hostname=True,
        )
        resource_kind = str(record.get("resource_kind") or rform).strip()

    ts = str(record.get("last_observed_at") or record.get("observed_at") or observed_at or _utc_now()).strip()
    _parse_timestamp(ts, f"{name}.observed_at")

    groups = [str(g) for g in (record.get("groups") or []) if g]
    service = str(
        record.get("service")
        or host_vars.get("service")
        or host_vars.get("role")
        or (groups[0] if groups else "")
        or record.get("name")
        or name
    ).strip()
    cluster = str(
        record.get("cluster")
        or host_vars.get("k8s_cluster_name")
        or host_vars.get("cluster")
        or ""
    ).strip()
    namespace = str(
        record.get("namespace")
        or host_vars.get("k8s_namespace")
        or host_vars.get("namespace")
        or ""
    ).strip()
    node = str(
        record.get("node")
        or record.get("node_id")
        or host_vars.get("node_id")
        or (record.get("name") or name if rform in {"vm", "k3s_node"} else "")
    ).strip()

    status = str(record.get("status") or record.get("observation_status") or "active").strip().lower()
    if status not in LIFECYCLE_STATES:
        raise ValueError(f"resource {name!r} status must be one of {sorted(LIFECYCLE_STATES)}, got {status!r}")

    return {
        "resource_key": rkey,
        "name": str(record.get("name") or name),
        "provider": provider,
        "account_or_project": acct_proj,
        "region": region,
        "resource_id": res_id,
        "environment": resolved_env,
        "runtime_form": rform,
        "resource_kind": resource_kind,
        "ssh_host": ssh_host,
        "primary_ip": primary_ip,
        "public_endpoint": record.get("public_endpoint") or record.get("uri") or record.get("public_ip"),
        "service": service,
        "cluster": cluster,
        "namespace": namespace,
        "node": node,
        "status": status,
        "observed_at": str(record.get("observed_at") or ts),
        "last_observed_at": ts,
    }


def resource_refs(resource_paths: str | list[str]) -> list[str]:
    """Keep provenance portable without embedding a workstation absolute path."""
    paths = resource_paths if isinstance(resource_paths, list) else resource_paths.split(",")
    refs = []
    for raw_path in paths:
        path = raw_path.strip()
        if not path:
            continue
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
    default_region: str | None = None,
    observed_at: str | None = None,
    serverless_resources: Mapping[str, Mapping[str, Any]] | None = None,
    legacy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a cmdb.v1 document while preserving legacy top-level records and deduplicating by resource_key."""
    resolved_env = infer_environment(resource_paths, environment)
    doc_ts = str(observed_at or _utc_now()).strip()
    _parse_timestamp(doc_ts, "observed_at")

    canonical_hosts: dict[str, Mapping[str, Any]] = {}
    canonical_serverless: dict[str, dict[str, Any]] = {}
    resource_index: dict[str, dict[str, Any]] = {}
    key_to_host_name: dict[str, str] = {}
    key_to_serverless_name: dict[str, str] = {}

    def _ingest_entry(entry_name: str, entry: Mapping[str, Any], *, force_serverless: bool = False) -> None:
        item = dict(entry)
        if force_serverless and "runtime_form" not in item and "resource_kind" not in item:
            item["runtime_form"] = "serverless"
            item["resource_kind"] = "serverless_service"
        normalized = normalize_resource_record(
            entry_name,
            item,
            cloud_provider=cloud_provider,
            environment=resolved_env,
            project_id=project_id,
            default_region=default_region,
            observed_at=doc_ts,
        )
        rkey = normalized["resource_key"]
        existing = resource_index.get(rkey)
        if existing is not None:
            if existing["environment"] != normalized["environment"]:
                raise ValueError(
                    f"duplicate resource_key {rkey} has conflicting environments: "
                    f"{existing['environment']!r} vs {normalized['environment']!r}"
                )
            existing_ts = _parse_timestamp(existing["last_observed_at"])
            new_ts = _parse_timestamp(normalized["last_observed_at"])
            if new_ts < existing_ts:
                return
            old_host_name = key_to_host_name.pop(rkey, None)
            if old_host_name and old_host_name != entry_name:
                canonical_hosts.pop(old_host_name, None)
            old_serverless_name = key_to_serverless_name.pop(rkey, None)
            if old_serverless_name and old_serverless_name != entry_name:
                canonical_serverless.pop(old_serverless_name, None)

        resource_index[rkey] = normalized
        if normalized["runtime_form"] == "serverless":
            serverless_entry = dict(entry)
            serverless_entry.setdefault("runtime_form", "serverless")
            serverless_entry.setdefault("resource_kind", normalized["resource_kind"])
            serverless_entry["ssh_host"] = None
            serverless_entry["primary_ip"] = None
            serverless_entry["resource_key"] = rkey
            serverless_entry["last_observed_at"] = normalized["last_observed_at"]
            canonical_serverless[entry_name] = serverless_entry
            key_to_serverless_name[rkey] = entry_name
        else:
            canonical_hosts[entry_name] = entry
            key_to_host_name[rkey] = entry_name

    for name, host in hosts.items():
        _ingest_entry(name, host, force_serverless=False)

    for name, s_item in (serverless_resources or {}).items():
        _ingest_entry(name, s_item, force_serverless=True)

    document: dict[str, Any] = dict(legacy or {})
    document.update(
        {
            "schema_version": SCHEMA_VERSION,
            "environment": resolved_env,
            "cloud_provider": cloud_provider,
            "source_resources": resource_refs(resource_paths),
            "observed_at": doc_ts,
            "last_observed_at": doc_ts,
            "hosts": dict(canonical_hosts),
            "serverless_resources": dict(canonical_serverless),
            "resource_index": dict(resource_index),
        }
    )
    if project_id:
        document["project_id"] = project_id

    # Compatibility for existing scripts and receipts. The canonical path is
    # document["hosts"], but old callers may still use document[host_name].
    for name, host in canonical_hosts.items():
        document[name] = host
    return document


def merge_documents(*documents: Mapping[str, Any]) -> dict[str, Any]:
    """Idempotently merge multiple cmdb.v1 documents for the same environment by resource_key."""
    if not documents:
        raise ValueError("at least one CMDB document is required")

    environments = {
        str(doc.get("environment") or "unknown").strip().lower()
        for doc in documents
        if str(doc.get("environment") or "unknown").strip().lower() != "unknown"
    }
    if len(environments) > 1:
        raise ValueError(f"cannot merge CMDB documents across environments: {sorted(environments)}")
    target_env = next(iter(environments), "unknown")

    merged_index: dict[str, dict[str, Any]] = {}
    merged_hosts: dict[str, Mapping[str, Any]] = {}
    merged_serverless: dict[str, dict[str, Any]] = {}
    key_to_host: dict[str, str] = {}
    key_to_serverless: dict[str, str] = {}
    sources: list[str] = []
    latest_ts: datetime | None = None
    latest_ts_str = _utc_now()

    first_provider = str(documents[0].get("cloud_provider") or "multi-cloud")
    first_project = documents[0].get("project_id")

    for doc in documents:
        if doc.get("schema_version") and doc.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {doc.get('schema_version')}")
        doc_env = str(doc.get("environment") or target_env).strip().lower()
        if target_env != "unknown" and doc_env != "unknown" and doc_env != target_env:
            raise ValueError(f"cross-environment document merge rejected: {doc_env!r} vs {target_env!r}")
        for src in doc.get("source_resources") or []:
            if src not in sources:
                sources.append(src)

        doc_ts_raw = doc.get("last_observed_at") or doc.get("observed_at") or _utc_now()
        doc_ts = _parse_timestamp(doc_ts_raw)
        if latest_ts is None or doc_ts > latest_ts:
            latest_ts = doc_ts
            latest_ts_str = str(doc_ts_raw)

        doc_provider = str(doc.get("cloud_provider") or first_provider)
        doc_project = doc.get("project_id") or first_project

        for h_name, h_rec in (doc.get("hosts") or {}).items():
            norm = normalize_resource_record(
                h_name,
                h_rec,
                cloud_provider=doc_provider,
                environment=target_env,
                project_id=doc_project,
                observed_at=str(doc_ts_raw),
            )
            rkey = norm["resource_key"]
            prev = merged_index.get(rkey)
            if prev is not None and _parse_timestamp(norm["last_observed_at"]) < _parse_timestamp(prev["last_observed_at"]):
                continue
            if rkey in key_to_host and key_to_host[rkey] != h_name:
                merged_hosts.pop(key_to_host[rkey], None)
            merged_index[rkey] = norm
            if norm["runtime_form"] == "serverless":
                merged_serverless[h_name] = dict(h_rec, resource_key=rkey, ssh_host=None, primary_ip=None)
                key_to_serverless[rkey] = h_name
            else:
                merged_hosts[h_name] = h_rec
                key_to_host[rkey] = h_name

        for s_name, s_rec in (doc.get("serverless_resources") or {}).items():
            norm = normalize_resource_record(
                s_name,
                s_rec,
                cloud_provider=doc_provider,
                environment=target_env,
                project_id=doc_project,
                observed_at=str(doc_ts_raw),
            )
            rkey = norm["resource_key"]
            prev = merged_index.get(rkey)
            if prev is not None and _parse_timestamp(norm["last_observed_at"]) < _parse_timestamp(prev["last_observed_at"]):
                continue
            if rkey in key_to_serverless and key_to_serverless[rkey] != s_name:
                merged_serverless.pop(key_to_serverless[rkey], None)
            merged_index[rkey] = norm
            merged_serverless[s_name] = dict(s_rec, resource_key=rkey, ssh_host=None, primary_ip=None)
            key_to_serverless[rkey] = s_name

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "environment": target_env,
        "cloud_provider": first_provider,
        "source_resources": sources,
        "observed_at": latest_ts_str,
        "last_observed_at": latest_ts_str,
        "hosts": merged_hosts,
        "serverless_resources": merged_serverless,
        "resource_index": merged_index,
    }
    if first_project:
        result["project_id"] = first_project
    for name, host in merged_hosts.items():
        result[name] = host
    return result


def write_document(path: str | os.PathLike[str], document: Mapping[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
