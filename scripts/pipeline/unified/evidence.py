"""Exact-set, current-run evidence. Never infer success from an empty directory."""
from __future__ import annotations

import hashlib
import json
import re
import ipaddress
from pathlib import Path

from .contracts import STAGES, digest, owner_match, read_json, require, write_json

SUCCESS = {"check": {"static_checked"}, "plan": {"planned", "verified_existing", "not_applicable"},
           "apply": {"applied_verified", "verified_existing", "not_applicable"},
           "destroy": {"destroyed_verified", "not_applicable"}}


def receipt_base(context, target, stage):
    spec = target["stages"][stage]
    return {
        "schema_version": 1, "correlation_id": context["correlation_id"],
        "run_id": context["run_id"], "run_attempt": context["run_attempt"],
        "workflow_ref": context["workflow_ref"], "workflow_sha": context["workflow_sha"],
        "gitops_sha": context["gitops_sha"], "iac_sha": context["iac_sha"],
        "contract_sha256": context["contract_sha256"],
        "manifest_sha256": spec.get("manifest_sha256", context["manifest_sha256"]),
        "requested_refs": context["requested_refs"],
        "target_id": target["id"], **{k: target[k] for k in ("environment", "project", "provider", "account", "workspace")},
        "stage": stage, "action": context["action"],
        "owner_action": f".github/actions/iac-{stage}",
        "state_key": spec.get("state", {}).get("key", ""),
        "result": "failed", "verification": {}, "plan_sha256": "", "inventory_sha256": "",
    }


def verify_receipt(context, target, stage, receipt):
    expected = receipt_base(context, target, stage)
    for field, value in expected.items():
        if field not in {"result", "verification", "plan_sha256", "inventory_sha256"}:
            require(receipt.get(field) == value, f"receipt binding mismatch: {target['id']}/{stage}/{field}")
    require(receipt.get("result") in SUCCESS[context["action"]], f"stage failed/blocked: {target['id']}/{stage}")
    require(receipt.get("verification", {}).get("contract") is True, "missing owner contract verification")
    require(receipt.get("verification", {}).get("cleanup") is True, "credential cleanup failed or missing")
    mode = target["stages"][stage]["mode"]
    if mode == "not_applicable":
        require(receipt.get("result") == "not_applicable" and receipt.get("reason") == target["stages"][stage]["reason"], "missing capability reason")
    else:
        require(receipt.get("verification", {}).get("identity") is True, "missing provider identity verification")
    if mode == "terraform" and not (stage == "bootstrap" and context["bootstrap_mode"] == "verify"):
        require(receipt.get("verification", {}).get("ownership") is True, "missing resource ownership verification")
        require(len(receipt.get("plan_sha256", "")) == 64, "missing saved plan digest")
        if context["action"] != "plan":
            require(receipt.get("verification", {}).get("convergence") is True, "missing target convergence")
        if stage == "bootstrap" and context["action"] == "apply":
            require(receipt.get("verification", {}).get("runtime_identity") is True, "runtime federation unverified")
            require(receipt.get("verification", {}).get("runtime_metadata_published") is True, "runtime metadata publication unverified")
            require(receipt.get("verification", {}).get("bootstrap_credential_removed") is True, "one-time bootstrap credential removal unverified")
    return receipt


def collect(context, root, stages=None):
    stages = context["stages"] if stages is None else stages
    expected = {(t["id"], stage): t for t in context["targets"] for stage in stages}
    found = {}
    for path in Path(root).rglob("receipt.json"):
        receipt = read_json(path)  # Malformed JSON is an error, never discarded.
        key = (receipt.get("target_id"), receipt.get("stage"))
        require(key in expected, "unexpected receipt target/stage")
        require(key not in found, "duplicate receipt")
        verify_receipt(context, expected[key], key[1], receipt)
        if receipt.get("inventory_sha256"):
            inventory = path.parent / "inventory.json"
            require(inventory.is_file() and digest(inventory) == receipt["inventory_sha256"], "inventory checksum mismatch")
        found[key] = (path, receipt)
    require(set(found) == set(expected), f"missing receipts: {sorted(set(expected) - set(found))}")
    return found


def guard_plan(target, stage, plan, action):
    spec = target["stages"][stage]
    changes = plan.get("resource_changes", [])
    counts = {"create": 0, "update": 0, "delete": 0}
    for item in changes:
        if item.get("mode") == "data":
            continue
        address = item["address"]
        require(owner_match(address, spec["owners"]), f"resource outside stage ownership: {address}")
        actions = item["change"]["actions"]
        for operation in counts:
            counts[operation] += operation in actions
        if "delete" in actions:
            require(not owner_match(address, spec.get("protected", [])), "protected resource deletion/replacement")
            require(item.get("type") not in {"google_compute_disk", "aws_ebs_volume", "linode_volume", "vultr_block_storage", "ucloud_udisk"}, "persistent disk deletion/replacement requires maintenance")
            require(action == "destroy", "ordinary plan/apply cannot delete or replace resources")
        if action == "destroy":
            require(set(actions) <= {"delete", "no-op", "read"}, "destroy plan contains forward mutations")
        if item.get("type") == "vultr_instance" and actions == ["update"]:
            before, after = item["change"].get("before") or {}, item["change"].get("after") or {}
            shapes = ["vc2-1c-1gb", "vc2-1c-2gb", "vc2-2c-4gb", "vc2-4c-8gb"]
            if before.get("plan") in shapes and after.get("plan") in shapes:
                require(shapes.index(after["plan"]) >= shapes.index(before["plan"]), "Vultr downgrade requires controlled replacement maintenance")
    return counts


def sanitize_inventory(raw):
    require(isinstance(raw, dict), "inventory must be a mapping")
    permitted = {"name", "fqdn", "label", "ip", "private_ip", "ipv6", "instance_id", "region", "type", "image", "groups", "ansible_user", "cloud_provider"}
    vars_allowed = {"role", "cloud_provider", "cloud_region", "plan", "image", "service_domains", "xconnect_role"}
    clean = {}
    for name, facts in raw.items():
        require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,252}", name), "invalid inventory hostname")
        require(isinstance(facts, dict), "invalid inventory host")
        for key in ("ip", "private_ip", "ipv6"):
            if facts.get(key):
                address = ipaddress.ip_address(facts[key])
                require(not address.is_unspecified and not address.is_loopback and not address.is_multicast, "invalid deployment address")
        require(all(isinstance(group, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,126}", group) for group in facts.get("groups", [])), "invalid inventory group")
        clean[name] = {key: value for key, value in facts.items() if key in permitted}
        clean[name]["host_vars"] = {key: value for key, value in facts.get("host_vars", {}).items() if key in vars_allowed}
    return clean


def summarize(context, evidence_root, needs, destination):
    expected_jobs = set(context["stages"] if context["action"] != "destroy" else ("destroy-" + s for s in context["stages"]))
    if context["action"] == "check":
        expected_jobs = set()
    require(needs.get("prepare", {}).get("result") == "success", "prepare failed or cancelled")
    for stage in STAGES:
        for job in (stage, "destroy-" + stage):
            wanted = "success" if job in expected_jobs else "skipped"
            require(needs.get(job, {}).get("result") == wanted, f"job {job} must be {wanted}")
    receipts = collect(context, evidence_root, [] if context["action"] == "check" else None)
    hosts = []
    inventory_set = {}
    for (target_id, stage), (path, receipt) in sorted(receipts.items()):
        if receipt["inventory_sha256"]:
            inventory = read_json(path.parent / "inventory.json")
            inventory_set[target_id] = inventory
            for name, facts in inventory.items():
                hosts.append({"target_id": target_id, "host": name, **facts})
    result = {"check": "static_checked", "plan": "planned", "apply": "applied_verified", "destroy": "destroyed_verified"}[context["action"]]
    aggregate = {"schema_version": 1, "result": result, "context": context,
                 "receipts": [item[1] for _, item in sorted(receipts.items())], "deploy_matrix": hosts,
                 "jobs": {key: ("success" if key in expected_jobs else "not_selected") for key in (*STAGES, *("destroy-" + s for s in STAGES))}}
    destination = Path(destination)
    write_json(destination / "summary.json", aggregate)
    write_json(destination / "inventory.json", inventory_set)
    (destination / "summary.md").write_text(f"## Multi-cloud IaC: {result}\n\nTargets: {len(context['targets'])}; verified stage receipts: {len(receipts)}.\n\nCloud resource convergence is separate from application acceptance.\n")
    return aggregate


def verify_summary(path, checksum, run_id, attempt, gitops_sha, iac_sha, manifest, action, correlation):
    require(digest(path) == checksum, "summary checksum mismatch")
    summary = read_json(path)
    context = summary["context"]
    unsigned = dict(context)
    contract_digest = unsigned.pop("contract_sha256")
    require(hashlib.sha256(json.dumps(unsigned, sort_keys=True).encode()).hexdigest() == contract_digest, "aggregate contract digest mismatch")
    expected_stages = list(STAGES) if context["stage_scope"] == "all" else [context["stage_scope"]]
    if action == "destroy":
        expected_stages.reverse()
    require(context["stages"] == expected_stages, "aggregate stage scope mismatch")
    for key, value in {"run_id": run_id, "run_attempt": attempt, "gitops_sha": gitops_sha,
                       "iac_sha": iac_sha, "manifest_path": manifest, "action": action,
                       "correlation_id": correlation}.items():
        require(context.get(key) == value, f"summary binding mismatch: {key}")
    expected = {(t["id"], s): t for t in context["targets"] for s in context["stages"]} if action != "check" else {}
    seen = set()
    for receipt in summary["receipts"]:
        key = receipt.get("target_id"), receipt.get("stage")
        require(key in expected and key not in seen, "unexpected/duplicate aggregate receipt")
        verify_receipt(context, expected[key], key[1], receipt)
        seen.add(key)
    require(seen == set(expected), "incomplete aggregate receipts")
    require(summary["result"] == {"check": "static_checked", "plan": "planned", "apply": "applied_verified", "destroy": "destroyed_verified"}[action], "wrong operation result")
    inventories = read_json(Path(path).parent / "inventory.json")
    for receipt in summary["receipts"]:
        if receipt["inventory_sha256"]:
            require(receipt["target_id"] in inventories, "missing aggregate inventory")
            data = json.dumps(inventories[receipt["target_id"]], sort_keys=True, indent=2) + "\n"
            require(hashlib.sha256(data.encode()).hexdigest() == receipt["inventory_sha256"], "aggregate inventory mismatch")
    require(summary["deploy_matrix"] == [
        {"target_id": target_id, "host": name, **facts}
        for target_id, inventory in sorted(inventories.items()) for name, facts in inventory.items()
    ], "deploy matrix differs from verified inventory")
    return summary
