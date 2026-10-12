#!/usr/bin/env python3
"""Reconcile only declared Accounts/Billing API aliases; never probe services.

Worker code and database cutover approval belong to the caller. This owner
checks the deployed Worker bindings/routes before touching DNS, and preserves
private checkpoints for provider recovery. Brand and Console are out of scope.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "gateway_dns_owner", Path(__file__).with_name("cloudflare-gateway-dns-upsert.py")
)
_owner = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _owner
_spec.loader.exec_module(_owner)
Cloudflare = _owner.Cloudflare
OperationError = _owner.OperationError
domain = _owner.domain
record_payload = _owner.record_payload
save_checkpoint = _owner.save_checkpoint


def require(condition, message):
    if not condition:
        raise OperationError(message)


def contract(config):
    require(config.get("kind") == "EdgeRoutingConfig", "routing config kind mismatch")
    env = config["metadata"]["environment"]
    require(env in {"uat", "prod"}, "explicit API environment required")
    spec = config["spec"]
    mode = spec["runtime"]["mode"]
    require(mode in {"serverless", "selfhost", "hybrid"}, "unknown runtime mode")
    dns = spec["runtime"]["routing"]["dns"]
    if dns.get("api_alias_mode") != "worker-routes-cname":
        return None  # A legacy declaration must not implicitly migrate live DNS.
    serverless = spec["serverless"]
    core = next(b["worker_name"] for b in serverless["edge_gateway"]["boundaries"] if b["id"] == "core")
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", core), "invalid core Worker name")
    aliases = dns.get("api_cname_records", {})
    require(len(aliases) == 2, "exactly Accounts and Billing aliases required")
    plans = []
    expected_hosts = {serverless["accounts_host"], serverless.get("billing_serverless_host", serverless["billing_host"])}
    for name, targets in aliases.items():
        name = domain(name)
        require(name.startswith(("accounts.", "billing.")), "only Accounts/Billing aliases may change")
        declared = spec["domains"][name]
        require(targets == {"serverless": declared["serverless"], "selfhost": declared["selfhost"]}, "API targets differ from domain declaration")
        serverless_target = domain(targets["serverless"])
        require(serverless_target in expected_hosts, "API Serverless target does not match Worker hosts")
        target = domain(targets["serverless" if mode == "serverless" else "selfhost"])
        require(dns["canonical_records"][name] == target and name != target, "canonical CNAME target mismatch")
        require(name.endswith(".svc.plus") if env == "prod" else name.endswith(".onwalk.net"), "API alias belongs to another environment zone")
        require(target.endswith("." + name.split(".", 1)[1]), "API target must stay in its declared zone")
        require(f"-{env}." in serverless_target and f"-{env}." in target, "API target must be environment qualified")
        plans.append({"name": name, "target": target, "serverless_target": serverless_target, "core": core})
    require({p["name"].split(".", 1)[0] for p in plans} == {"accounts", "billing"}, "both API boundaries required")
    return {"environment": env, "mode": mode, "plans": plans, "serverless": serverless}


def domains(client):
    result = client.request("GET", f"/accounts/{client.account_id}/workers/domains")
    require(isinstance(result, list) and len(result) < 100, "ambiguous or truncated Worker domain list")
    return result


def domain_for(items, name):
    matches = [d for d in items if d.get("hostname") == name]
    require(len(matches) <= 1, "multiple Worker domain bindings for one API hostname")
    return matches[0] if matches else None


def attach(client, binding):
    payload = {key: binding[key] for key in ("hostname", "service", "zone_id")}
    result = client.request("PUT", f"/accounts/{client.account_id}/workers/domains", payload)
    require(isinstance(result, dict) and result.get("hostname") == binding["hostname"] and result.get("service") == binding["service"], "Worker domain response identity mismatch")
    return result


def verify_workers(client, config, resolved, revision):
    require(re.fullmatch(r"[0-9a-f]{40}", revision or ""), "exact deployed gateway revision required")
    defaults = resolved["serverless"]["edge_gateway"]["defaults"]
    expected = {
        "RUNTIME_MODE": resolved["mode"], "GATEWAY_REVISION": revision,
        "PRIMARY_UPSTREAM": defaults["primary_upstream"], "FALLBACK_UPSTREAM": defaults["fallback_upstream"],
        "BILLING_PRIMARY_UPSTREAM": defaults["billing_primary_upstream"], "BILLING_FALLBACK_UPSTREAM": defaults["billing_fallback_upstream"],
    }
    for boundary in resolved["serverless"]["edge_gateway"]["boundaries"]:
        worker = boundary["worker_name"]
        require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", worker), "invalid Worker name")
        settings = client.request("GET", f"/accounts/{client.account_id}/workers/scripts/{worker}/settings")
        values = {b["name"]: b.get("text") for b in settings.get("bindings", []) if b.get("type") == "plain_text"}
        require(all(values.get(k) == v for k, v in expected.items()), "deployed Worker revision/mode/origins do not match routing plan")
    for plan in resolved["plans"]:
        zone = client.zone_id(plan["name"].split(".", 1)[1])
        routes = client.request("GET", f"/zones/{zone}/workers/routes")
        require(isinstance(routes, list), "invalid Worker Routes response")
        actual = {r["pattern"]: r.get("script") for r in routes}
        if plan["name"].startswith("billing."):
            require(actual.get(plan["name"] + "/*") == plan["core"], "canonical Billing Core route missing")
        else:
            for boundary in resolved["serverless"]["edge_gateway"]["boundaries"]:
                for suffix in boundary.get("routes", [boundary.get("route")]):
                    require(suffix and actual.get(plan["name"] + suffix) == boundary["worker_name"], "canonical Accounts boundary route missing")
        plan["zone_id"] = zone


def preflight(client, plan, all_domains):
    zone, name = plan["zone_id"], plan["name"]
    canonical_binding = domain_for(all_domains, name)
    target_binding = domain_for(all_domains, plan["serverless_target"])
    for binding in (canonical_binding, target_binding):
        if binding:
            require(binding.get("service") == plan["core"] and binding.get("zone_id") == zone, "API domain is owned by another Worker/zone")
    records = client.records(zone, name)
    require(len(records) <= 1, "refusing multiple canonical API DNS records")
    if records:
        record = records[0]
        owned_cname = record.get("type") == "CNAME" and record.get("content") in {plan["serverless_target"], plan["target"]}
        managed_worker_record = canonical_binding and record.get("type") == "AAAA" and record.get("content") == "100::" and record.get("proxied") is True
        require(owned_cname or managed_worker_record, "refusing unrelated canonical API DNS record")
    if plan["target"] != plan["serverless_target"]:
        require(domain_for(all_domains, plan["target"]) is None, "Selfhost origin must not loop through a Worker domain")
        target_records = client.records(zone, plan["target"])
        require(len(target_records) == 1 and target_records[0].get("type") in {"A", "AAAA", "CNAME"}, "Selfhost origin DNS is not declared and deployed")
    if not target_binding:
        require(not client.records(zone, plan["serverless_target"]), "refusing to overwrite unrelated qualified API origin DNS")
    return {"plan": plan, "before_records": records, "before_domain": canonical_binding, "before_target_domain": target_binding, "done": False}


def recover(client, state):
    """Restore only values this operation owns; refuse concurrent modifications."""
    for item in reversed(state["items"]):
        if not item.get("started"):
            continue
        plan = item["plan"]
        current = client.records(plan["zone_id"], plan["name"])
        unchanged = [record_payload(r) for r in current] == [record_payload(r) for r in item["before_records"]]
        if not unchanged:
            for record in current:
                require(record.get("type") == "CNAME" and record.get("content") == plan["target"] and
                        record.get("comment") == "GitOps API alias via Edge Gateway" and record.get("proxied") is True,
                        "API DNS changed concurrently; recovery stopped")
                client.delete(plan["zone_id"], record["id"])
        if item["before_domain"]:
            binding = domain_for(domains(client), plan["name"])
            require(not binding or binding.get("service") == plan["core"], "canonical Worker domain changed concurrently")
            if not binding:
                attach(client, item["before_domain"])
        elif not unchanged:
            for record in item["before_records"]:
                client.create(plan["zone_id"], record_payload(record))
        if item.get("created_target"):
            binding = domain_for(domains(client), plan["serverless_target"])
            require(not binding or binding["service"] == plan["core"], "qualified API domain changed concurrently")
            if binding:
                client.request("DELETE", f"/accounts/{client.account_id}/workers/domains/{binding['id']}")


def reconcile(client, config, revision, checkpoint):
    resolved = contract(config)
    if resolved is None:
        return {"status": "legacy-declaration-unchanged"}
    require(checkpoint.is_absolute() and not checkpoint.is_symlink() and not checkpoint.exists(), "new private API checkpoint path required")
    verify_workers(client, config, resolved, revision)
    all_domains = domains(client)
    state = {"schema": "api-alias-checkpoint/v1", "environment": resolved["environment"], "revision": revision,
             "items": [preflight(client, p, all_domains) for p in resolved["plans"]]}
    save_checkpoint(checkpoint, state)
    try:
        for item in state["items"]:
            plan = item["plan"]
            before = item["before_records"]
            if (item["before_target_domain"] and not item["before_domain"] and len(before) == 1 and
                    before[0].get("type") == "CNAME" and before[0].get("content") == plan["target"] and before[0].get("proxied") is True):
                item["done"] = True
                save_checkpoint(checkpoint, state)
                continue
            item["started"] = True
            save_checkpoint(checkpoint, state)
            if not item["before_target_domain"]:
                # Persist intent before the API: an interrupted reply may have
                # already created the provider resource.
                item["created_target"] = True
                save_checkpoint(checkpoint, state)
                attach(client, {"hostname": plan["serverless_target"], "service": plan["core"], "zone_id": plan["zone_id"]})
            if item["before_domain"]:
                client.request("DELETE", f"/accounts/{client.account_id}/workers/domains/{item['before_domain']['id']}")
            desired = {"name": plan["name"], "type": "CNAME", "content": plan["target"], "proxied": True, "ttl": 1,
                       "comment": "GitOps API alias via Edge Gateway"}
            current = client.records(plan["zone_id"], plan["name"])
            if current:
                require(len(current) == 1 and current[0]["type"] == "CNAME", "unexpected DNS after Worker domain detach")
                client.update(plan["zone_id"], current[0]["id"], desired)
            else:
                client.create(plan["zone_id"], desired)
            actual = client.records(plan["zone_id"], plan["name"])
            require(len(actual) == 1 and actual[0]["type"] == "CNAME" and actual[0]["content"] == plan["target"] and actual[0]["proxied"] is True, "API CNAME provider verification failed")
            item["done"] = True
            save_checkpoint(checkpoint, state)
    except OperationError:
        recover(client, state)
        state["restored"] = True
        save_checkpoint(checkpoint, state)
        raise
    state["success"] = True
    save_checkpoint(checkpoint, state)
    return {"schema": "api-alias-reconcile/v1", "environment": resolved["environment"], "mode": resolved["mode"], "revision": revision,
            "aliases": {p["name"]: p["target"] for p in resolved["plans"]}, "provider_verified": True, "business_verified": False}


def main():
    config = json.loads(Path(os.environ["EDGE_GATEWAY_CONFIG_FILE"]).read_text())
    client = Cloudflare(os.environ["CLOUDFLARE_API_TOKEN"], os.environ["CLOUDFLARE_ACCOUNT_ID"])
    result = reconcile(client, config, os.environ.get("GATEWAY_REVISION", ""), Path(os.environ["API_ALIAS_CHECKPOINT"]))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OperationError, KeyError, ValueError, TypeError, OSError):
        raise SystemExit("API alias provider operation failed; checkpoint retained; private details withheld")
