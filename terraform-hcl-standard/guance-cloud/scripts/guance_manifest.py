#!/usr/bin/env python3
"""Validate the GitOps Guance manifest and expand it into explicit HCL resource models.

Every loop over resources happens here; the generated Terraform stays flat.
"""
import re
from datetime import datetime
from pathlib import Path

import yaml

from hcl import Raw, to_hcl
from secret_scan import scan_keys, scan_text

KINDS = ("dashboards", "notify_objects", "alert_policies", "monitors", "mutes")
GLOBAL_REQUIRED = {"environment", "workspace_alias", "endpoint", "region"}
GLOBAL_OPTIONAL = {"project"}
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
COMPONENT_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
NOTIFY_TYPES = frozenset(
    {
        "dingTalkRobot", "HTTPRequest", "wechatRobot", "mailGroup", "feishuRobot", "sms", "vms",
        "simpleHTTPRequest", "slackIncomingWebhook", "teamsWorkflowWebhook", "googleChatWebhook", "telegramBot",
    }
)
ALERT_STATUSES = frozenset({"critical", "error", "warning", "info", "ok", "nodata"})
TIME_FORMAT = "%Y/%m/%d %H:%M:%S"
EVERY_RE = re.compile(r"^[1-9][0-9]*[smhd]$")
MAX_MUTE_SECONDS = 8 * 3600
MONITOR_STATUS_ENABLED = 0
MONITOR_STATUS_DISABLED = 2
PLACEHOLDER = "REPLACE_"


def _fail(message):
    raise ValueError(message)


def _object(value, label, required, optional=()):
    if not isinstance(value, dict):
        _fail(f"{label} must be an object")
    missing = set(required) - set(value)
    extra = set(value) - set(required) - set(optional)
    if missing or extra:
        _fail(f"{label} requires {sorted(required)}; missing {sorted(missing)}, unexpected {sorted(extra)}")
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label} must be a non-empty string")
    return value


def _int(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(f"{label} must be an integer >= {minimum}")
    return value


def _strings(value, label, allow_empty=True):
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        _fail(f"{label} must be a list of non-empty strings")
    if not value and not allow_empty:
        _fail(f"{label} must not be empty")
    return value


def _entries(document, kind):
    value = document.get(kind, [])
    if not isinstance(value, list):
        _fail(f"{kind} must be a list")
    return value


def _ref(value, label, known):
    if value not in known:
        _fail(f"{label} references unknown id {value!r}")
    return value


def _timestamp(value, label):
    try:
        return datetime.strptime(_text(value, label), TIME_FORMAT)
    except ValueError:
        _fail(f"{label} must use YYYY/MM/DD HH:MM:SS")


def load_manifest(path):
    document = yaml.safe_load(Path(path).read_text())
    return validate_manifest(document)


def validate_manifest(document):
    if not isinstance(document, dict) or not {"global", "dashboards"} <= set(document) or set(document) - set(KINDS) - {"global"}:
        _fail("manifest requires global and dashboards; optional lists: " + ", ".join(KINDS[1:]))
    leaked = scan_keys(document)
    if leaked:
        _fail("credential-like keys are not allowed in the manifest (inject them from Vault): " + ", ".join(leaked))
    if scan_text(yaml.safe_dump(document)):
        _fail("credential-shaped values are not allowed in the manifest")
    config = _object(document["global"], "global", GLOBAL_REQUIRED, GLOBAL_OPTIONAL)
    if config["environment"] != "uat":
        _fail("first rollout supports UAT only; PROD requires the promotion gate (docs/prod-promotion-gate.md)")
    if not isinstance(config["endpoint"], str) or not config["endpoint"].startswith("https://"):
        _fail("endpoint must use HTTPS")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", _text(config["workspace_alias"], "workspace_alias")):
        _fail("workspace_alias must be a stable logical alias")
    _text(config["region"], "region")
    if "project" in config and not COMPONENT_RE.fullmatch(_text(config["project"], "project")):
        _fail("project must match " + COMPONENT_RE.pattern)

    seen = {}

    def register(kind, entry):
        identifier = entry["id"]
        if not isinstance(identifier, str) or not ID_RE.fullmatch(identifier):
            _fail(f"{kind} id {identifier!r} must be a lowercase HCL identifier")
        if identifier in seen:
            _fail(f"id {identifier!r} is used by both {seen[identifier]} and {kind}; ids are unique across kinds")
        seen[identifier] = kind

    for entry in _entries(document, "dashboards"):
        _object(entry, "dashboard", {"id", "name", "description", "tags", "template"})
        register("dashboards", entry)
        _text(entry["name"], "dashboard name")
        _strings(entry["tags"], "dashboard tags")
        if not isinstance(entry["template"], dict):
            _fail("template must be an object")
    if not document["dashboards"]:
        _fail("at least one dashboard is required")

    for entry in _entries(document, "notify_objects"):
        _object(entry, "notify_object", {"id", "name", "type"})
        register("notify_objects", entry)
        _text(entry["name"], "notify_object name")
        if entry["type"] not in NOTIFY_TYPES:
            _fail(f"notify_object type must be one of {sorted(NOTIFY_TYPES)}")
    notify_ids = {item["id"] for item in _entries(document, "notify_objects")}

    for entry in _entries(document, "alert_policies"):
        _object(
            entry, "alert_policy", {"id", "name", "description", "timezone", "routes"},
            {"agg_interval", "silent_timeout", "agg_fields"},
        )
        register("alert_policies", entry)
        _text(entry["name"], "alert_policy name")
        _text(entry["timezone"], "alert_policy timezone")
        for field in ("agg_interval", "silent_timeout"):
            if field in entry:
                _int(entry[field], f"alert_policy {field}")
        if "agg_fields" in entry:
            _strings(entry["agg_fields"], "alert_policy agg_fields")
        if not isinstance(entry["routes"], list) or not entry["routes"]:
            _fail("alert_policy requires at least one route")
        for route in entry["routes"]:
            _object(route, "alert_policy route", {"name", "notify_objects", "status"})
            _text(route["name"], "route name")
            for notify in _strings(route["notify_objects"], "route notify_objects", allow_empty=False):
                _ref(notify, "route notify_objects", notify_ids)
            statuses = _text(route["status"], "route status").split(",")
            if statuses != ["All"] and not set(statuses) <= ALERT_STATUSES:
                _fail(f"route status must be 'All' or comma-separated values from {sorted(ALERT_STATUSES)}")
    policy_ids = {item["id"] for item in _entries(document, "alert_policies")}

    for entry in _entries(document, "monitors"):
        _validate_monitor(entry, policy_ids)
        register("monitors", entry)
    for entry in _entries(document, "mutes"):
        _validate_mute(entry, policy_ids)
        register("mutes", entry)
    return document


def _validate_monitor(entry, policy_ids):
    _object(
        entry, "monitor",
        {"id", "title", "message", "every", "interval", "recover_need_period_count", "group_by", "targets", "rules", "tags",
         "alert_policies", "baseline"},
    )
    _text(entry["title"], "monitor title")
    _text(entry["message"], "monitor message")
    if not EVERY_RE.fullmatch(str(entry["every"])):
        _fail("monitor every must look like 1m, 5m or 1h")
    _int(entry["interval"], "monitor interval", 1)
    _int(entry["recover_need_period_count"], "monitor recover_need_period_count", 1)
    _strings(entry["group_by"], "monitor group_by")
    _strings(entry["tags"], "monitor tags")
    for policy in _strings(entry["alert_policies"], "monitor alert_policies", allow_empty=False):
        _ref(policy, "monitor alert_policies", policy_ids)
    aliases = set()
    if not isinstance(entry["targets"], list) or not entry["targets"]:
        _fail("monitor requires at least one target")
    for target in entry["targets"]:
        _object(target, "monitor target", {"alias", "dql", "qtype"})
        aliases.add(_text(target["alias"], "target alias"))
        _text(target["dql"], "target dql")
        _text(target["qtype"], "target qtype")
    if not isinstance(entry["rules"], list) or not entry["rules"]:
        _fail("monitor requires at least one rule")
    for rule in entry["rules"]:
        _object(rule, "monitor rule", {"status", "condition_logic", "conditions"})
        _text(rule["status"], "rule status")
        if rule["condition_logic"] not in ("and", "or"):
            _fail("rule condition_logic must be and/or")
        if not isinstance(rule["conditions"], list) or not rule["conditions"]:
            _fail("rule requires conditions")
        for condition in rule["conditions"]:
            _object(condition, "rule condition", {"alias", "operator", "operands"})
            _ref(condition["alias"], "condition alias", aliases)
            _text(condition["operator"], "condition operator")
            _strings([str(item) for item in condition["operands"]], "condition operands", allow_empty=False)
    baseline = entry["baseline"]
    if not isinstance(baseline, dict) or baseline.get("status") not in ("pending", "measured"):
        _fail("monitor baseline.status must be pending or measured")
    if baseline["status"] == "pending":
        _object(baseline, "monitor baseline", {"status"})
    else:
        _object(baseline, "monitor baseline", {"status", "measured_at", "window", "source", "summary"})
        for field in ("window", "source", "summary"):
            _text(baseline[field], f"baseline {field}")
        try:
            datetime.strptime(str(baseline["measured_at"]), "%Y-%m-%d")
        except ValueError:
            _fail("baseline measured_at must use YYYY-MM-DD")
        blob = yaml.safe_dump({k: entry[k] for k in ("targets", "rules", "message", "title")})
        if PLACEHOLDER in blob:
            _fail(f"monitor {entry['id']} has measured baseline but still contains {PLACEHOLDER} placeholders")


def _validate_mute(entry, policy_ids):
    _object(entry, "mute", {"id", "name", "description", "policy", "timezone", "start", "end", "tags"})
    _text(entry["name"], "mute name")
    _ref(entry["policy"], "mute policy", policy_ids)
    _text(entry["timezone"], "mute timezone")
    start, end = _timestamp(entry["start"], "mute start"), _timestamp(entry["end"], "mute end")
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        _fail("mute end must be after start")
    if seconds > MAX_MUTE_SECONDS:
        _fail(f"mute window must not exceed {MAX_MUTE_SECONDS // 3600} hours; use a new GitOps change per release")
    tags = entry["tags"]
    if not isinstance(tags, dict) or not tags:
        _fail("mute tags must scope the silence to specific events (an unscoped mute is not allowed)")
    for key, values in tags.items():
        _text(key, "mute tag key")
        _strings(values, f"mute tag {key}", allow_empty=False)


def notify_variable(identifier):
    return f"guance_notify_{identifier}_opt_set"


def build_model(document):
    """Expand the manifest into per-resource attribute dictionaries."""
    model = {kind: [] for kind in KINDS}
    for item in document["dashboards"]:
        model["dashboards"].append(
            {
                "id": item["id"],
                "attrs": {
                    "name": item["name"],
                    "desc": item["description"],
                    "is_public": 0,
                    "tag_names": item["tags"],
                    "template_info": Raw("jsonencode(" + _hcl_literal(item["template"]) + ")"),
                },
            }
        )
    for item in document.get("notify_objects", []):
        model["notify_objects"].append(
            {
                "id": item["id"],
                "variable": notify_variable(item["id"]),
                "attrs": {
                    "name": item["name"],
                    "type": item["type"],
                    # The provider refreshes opt_set as Go json.Marshal output (sorted keys, compact,
                    # <>& escaped); jsonencode(jsondecode()) yields the same bytes, keeping re-plans empty.
                    "opt_set": Raw(f"jsonencode(jsondecode(var.{notify_variable(item['id'])}))"),
                    "open_permission_set": False,
                },
            }
        )
    for item in document.get("alert_policies", []):
        targets = []
        for route in item["routes"]:
            targets.append(
                {
                    "name": route["name"],
                    "targets": [
                        {
                            "to": [Raw(f"guance_notify_object.{notify}.uuid") for notify in route["notify_objects"]],
                            "status": route["status"],
                        }
                    ],
                }
            )
        alert_opt = {"alert_type": "status", "ignore_ok": False, "alert_target": targets}
        for field in ("agg_interval", "silent_timeout", "agg_fields"):
            if field in item:
                alert_opt[field] = item[field]
        model["alert_policies"].append(
            {
                "id": item["id"],
                "attrs": {
                    "name": item["name"],
                    "desc": item["description"],
                    "rule_timezone": item["timezone"],
                    "alert_opt": alert_opt,
                },
            }
        )
    for item in document.get("monitors", []):
        enabled = item["baseline"]["status"] == "measured"
        script = {
            "type": "simpleCheck",
            "title": item["title"],
            "message": item["message"],
            "every": item["every"],
            "interval": item["interval"],
            "recover_need_period_count": item["recover_need_period_count"],
            "disable_check_end_time": False,
            "group_by": item["group_by"],
            "targets": item["targets"],
            "checker_opt": {
                "info_event": False,
                "rules": [
                    {
                        "status": rule["status"],
                        "condition_logic": rule["condition_logic"],
                        "conditions": [
                            {"alias": c["alias"], "operator": c["operator"], "operands": [str(o) for o in c["operands"]]}
                            for c in rule["conditions"]
                        ],
                    }
                    for rule in item["rules"]
                ],
            },
            "channels": [],
            "at_accounts": [],
            "at_no_data_accounts": [],
        }
        model["monitors"].append(
            {
                "id": item["id"],
                "attrs": {
                    "type": "trigger",
                    # A monitor stays disabled until its threshold rests on a measured baseline.
                    "status": MONITOR_STATUS_ENABLED if enabled else MONITOR_STATUS_DISABLED,
                    "tags": item["tags"],
                    "open_permission_set": False,
                    "alert_policy_uuids": [Raw(f"guance_alert_policy.{p}.uuid") for p in item["alert_policies"]],
                    "extend": Raw(
                        "jsonencode("
                        + _hcl_literal({"isNeedCreateIssue": False, "issueLevelUUID": "", "needRecoverIssue": False})
                        + ")"
                    ),
                    "json_script": script,
                },
            }
        )
    for item in document.get("mutes", []):
        model["mutes"].append(
            {
                "id": item["id"],
                "attrs": {
                    "name": item["name"],
                    "description": item["description"],
                    "type": "alertPolicy",
                    "timezone": item["timezone"],
                    "mute_ranges": [{"alert_policy_uuid": Raw(f"guance_alert_policy.{item['policy']}.uuid")}],
                    "repeat_time_set": 0,
                    "start_time": item["start"],
                    "end_time": item["end"],
                    "tags": item["tags"],
                    "enabled": True,
                },
            }
        )
    return model


def _hcl_literal(value):
    """Render a top-level attribute value (depth 1) as an HCL literal."""
    return to_hcl(value, 1)
