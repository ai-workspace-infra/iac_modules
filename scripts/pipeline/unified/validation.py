"""Isolated candidate compute cleanup; source states are read-only witnesses."""
from __future__ import annotations

import hashlib
import json
import re

import yaml

from .contracts import digest, owner_match, require, source_file


def validate_candidate(target, gitops_root):
    validation = target.get("validation")
    if validation is None:
        return
    require(isinstance(validation, dict) and validation.get("mode") == "cleanroom", "unknown validation mode")
    require(target["provider"] == "akamai-cloud", "validation compute cleanup currently supports Akamai only")
    path = source_file(gitops_root, validation.get("source_manifest"))
    source_doc = yaml.safe_load(path.read_text())
    require(isinstance(source_doc, dict) and source_doc.get("kind") == "IaCPipelineTargets" and source_doc.get("apiVersion") == "gitops.svc.plus/v1alpha1", "validation source must be a target declaration")
    matches = [item for item in source_doc.get("targets", []) if item.get("id") == validation.get("source_target")]
    require(len(matches) == 1 and not matches[0].get("validation"), "one serving source target required")
    source = matches[0]
    from .contracts import validate_target
    validate_target(source, gitops_root)
    require(target["environment"] == source["environment"] and target["project"] == source["project"], "validation source must share the declared environment/project")
    spec, source_spec = target["stages"]["resources"], source["stages"]["resources"]
    require(spec.get("mode") == "terraform" and source_spec.get("mode") == "terraform", "validation needs explicit candidate/source state owners")
    require(target["workspace"] != source["workspace"], "validation and serving source namespaces must differ")
    require(spec["state"]["key"] != source_spec["state"]["key"], "validation cannot share serving source state")
    require(spec["manifest"] != source_spec["manifest"], "validation cannot use serving source resources")
    require(not spec.get("shared") and not spec.get("external_references"), "validation cannot own shared/external resources")
    owners = validation.get("destroy_owners")
    require(isinstance(owners, list) and len(owners) == 1 and re.fullmatch(r"module\.compute_[A-Za-z0-9_]+", owners[0]), "validation must select exactly one compute module")
    require(owners[0] in spec["owners"] and not owner_match(owners[0], spec.get("protected", [])), "validation compute owner is not authorized")
    resource = yaml.safe_load(source_file(gitops_root, spec["manifest"]).read_text())
    global_config = resource.get("global", {})
    require(global_config.get("workspace") == target["workspace"] and global_config.get("environment") == target["environment"], "validation resource identity mismatch")
    require(global_config.get("provider") == target["provider"] and global_config.get("account") == target["account"], "validation provider/account mismatch")
    require(not global_config.get("manage_account_ssh_keys"), "validation cannot manage account identities")
    require(global_config.get("prevent_destroy") is True, "validation must retain default deletion protection")
    hosts = resource.get("hosts", [])
    require(len(hosts) == 1 and not resource.get("volumes") and not resource.get("storage"), "validation cleanup requires one host and no independent storage")
    host = hosts[0]
    require(not host.get("volume"), "validation cannot own an attached data volume")
    require("generation_candidate" in host.get("groups", []), "serving hosts cannot enter validation cleanup")
    values = host.get("host_vars", {})
    require(values.get("public_dns_cutover") is False and values.get("database_background_writers") is False, "validation requires isolated traffic and writers")
    require(values.get("target_generation") and values.get("source_generation") and values["target_generation"] != values["source_generation"], "source/target generations must differ")
    source_resource = yaml.safe_load(source_file(gitops_root, source_spec["manifest"]).read_text())
    require(host.get("name") not in {item.get("name") for item in source_resource.get("hosts", [])}, "candidate hostname overlaps serving source")
    prefix = global_config.get("name_prefix", "")
    validation["expected_instance"] = {"label": prefix + "-" + host["name"] if prefix else host["name"],
        "region": host.get("region", global_config.get("region"))}
    require(validation["expected_instance"]["region"], "candidate region is required")
    validation["source_binding"] = {
        "manifest_sha256": digest(path), "state": source_spec["state"], "owners": source_spec["owners"],
        **{key: source[key] for key in ("environment", "project", "provider", "account", "workspace")},
    }


def state_resources(state):
    result = {}
    for resource in state.get("resources", []):
        if resource.get("mode", "managed") != "managed":
            continue
        base = ".".join(filter(None, (resource.get("module"), resource["type"], resource["name"])))
        for instance in resource.get("instances", []):
            suffix = "[" + json.dumps(instance["index_key"]) + "]" if "index_key" in instance else ""
            address = base + suffix
            provider = re.search(r'provider\["([^"\]]+)"\]', resource["provider"])
            require(provider, "state provider identity is incomplete")
            identity = (provider.group(1), resource["type"], str(instance.get("attributes", {}).get("id", "")))
            require(identity[2] and address not in result, "state resource identity is incomplete")
            result[address] = identity
    return result


def isolated_states(target, candidate, source):
    require(candidate.get("lineage") and source.get("lineage") and candidate["lineage"] != source["lineage"], "candidate/source state lineage must differ")
    current, serving = state_resources(candidate), state_resources(source)
    require(current and serving, "both candidate and serving source state must exist")
    require(all(owner_match(key, target["validation"]["source_binding"]["owners"]) for key in serving), "serving source state does not match its declared ownership")
    require(not set(current.values()) & set(serving.values()), "candidate state contains serving source resources")
    owners = target["validation"]["destroy_owners"]
    selected = {key: value for key, value in current.items() if owner_match(key, owners)}
    require(len(selected) == 1 and next(iter(selected.values()))[1] == "linode_instance", "exactly one candidate instance must be present")
    require(all(owner_match(key, target["stages"]["resources"]["owners"]) for key in current), "candidate state contains undeclared resources")
    require(all(any(owner_match(key, [owner]) for key in current) for owner in target["stages"]["resources"].get("protected", [])), "retained protected resource is missing from candidate state")
    return current, selected


def verify_retained(before, after, owners):
    expected = {key: value for key, value in before.items() if not owner_match(key, owners)}
    require(state_resources(after) == expected, "validation cleanup changed retained resources")


def state_digest(state):
    # Terraform emits check_results and their objects in Go map iteration order.
    # Only these address-keyed sets are unordered; resource attribute arrays are
    # semantically ordered and must continue to affect the witness digest.
    normalized = dict(state)
    if isinstance(state.get("check_results"), list):
        checks = []
        for item in state["check_results"]:
            check = dict(item)
            if isinstance(check.get("objects"), list):
                check["objects"] = sorted(check["objects"], key=lambda value: json.dumps(value, sort_keys=True))
            checks.append(check)
        normalized["check_results"] = sorted(checks, key=lambda value: json.dumps(value, sort_keys=True))
    return hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
