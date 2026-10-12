#!/usr/bin/env python3
"""Render Guance UAT dashboards and merge runtime resource identities."""
import argparse
import json
import re
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]


def load_manifest(path):
    document = yaml.safe_load(Path(path).read_text())
    if not isinstance(document, dict) or set(document) != {"global", "dashboards"}:
        raise ValueError("manifest requires exactly global and dashboards")
    config = document["global"]
    if set(config) != {"environment", "workspace_alias", "endpoint", "region"}:
        raise ValueError("global requires environment, workspace_alias, endpoint, region")
    if config["environment"] != "uat":
        raise ValueError("first rollout supports UAT only")
    if not isinstance(config["endpoint"], str) or not config["endpoint"].startswith("https://"):
        raise ValueError("endpoint must use HTTPS")
    ids = set()
    for entry in document["dashboards"]:
        if set(entry) != {"id", "name", "description", "tags", "template"}:
            raise ValueError("dashboard requires id, name, description, tags, template")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", entry["id"]) or entry["id"] in ids:
            raise ValueError("dashboard ids must be unique HCL identifiers")
        ids.add(entry["id"])
        if not isinstance(entry["template"], dict):
            raise ValueError("template must be an object")
    if not ids:
        raise ValueError("at least one dashboard is required")
    return document


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["render", "inventory"])
    parser.add_argument("--resources", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--outputs", help="terraform output -json file for inventory")
    args = parser.parse_args()
    document = load_manifest(args.resources)
    target = Path(args.workdir)
    target.mkdir(parents=True, exist_ok=True)
    if args.command == "render":
        env = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
        env.filters["hcl"] = lambda value: json.dumps(value, ensure_ascii=False).replace("${", "$${").replace("%{", "%%{")
        template = (ROOT / "templates/resources.tf.j2").read_text()
        content = env.from_string(template).render(dashboards=document["dashboards"])
        for name in ("provider.tf", "variables.tf"):
            (target / name).write_text((ROOT / "templates" / name).read_text())
        (target / "generated_resources.tf").write_text(content)
        config = document["global"]
        (target / "terraform.auto.tfvars.json").write_text(json.dumps({"guance_endpoint": config["endpoint"], "guance_region": config["region"]}, indent=2) + "\n")
    else:
        if not args.outputs:
            parser.error("inventory requires --outputs")
        runtime = json.loads(Path(args.outputs).read_text())["cmdb_runtime"]["value"]
        declared = {item["id"] for item in document["dashboards"]}
        if set(runtime) != declared:
            raise ValueError("runtime resources do not match manifest")
        records = []
        for item in document["dashboards"]:
            fact = runtime[item["id"]]
            if not fact.get("uuid") or not fact.get("workspace_uuid"):
                raise ValueError("missing remote UUID")
            records.append({"id": item["id"], "name": item["name"], "type": "dashboard", "environment": "uat", "workspace_alias": document["global"]["workspace_alias"], "uuid": fact["uuid"], "workspace_uuid": fact["workspace_uuid"]})
        (target / "cmdb.json").write_text(json.dumps({"resources": records}, indent=2) + "\n")


if __name__ == "__main__":
    main()
