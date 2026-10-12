#!/usr/bin/env python3
"""Render Guance UAT resources from a GitOps manifest and merge runtime resource identities.

Subcommands:
  render     manifest -> explicit HCL + tfvars in --workdir
  inventory  manifest + `terraform output -json` -> cmdb.json (observability resources only)
  import     manifest + {id: uuid} JSON of pre-existing remote objects -> generated_imports.tf
  state-key  print the canonical remote state key
"""
import argparse
import json
import re
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from guance_manifest import build_model, load_manifest
from hcl import hcl_body
from state_contract import canonical_state_key

ROOT = Path(__file__).resolve().parents[1]
STATIC_TEMPLATES = ("provider.tf", "variables.tf", "backend.tf")
# manifest kind -> (Terraform resource type, CMDB resource type, display name field)
KIND_TYPES = {
    "dashboards": ("guance_dashboard", "dashboard", "name"),
    "notify_objects": ("guance_notify_object", "notify_object", "name"),
    "alert_policies": ("guance_alert_policy", "alert_policy", "name"),
    "monitors": ("guance_monitor", "monitor", "title"),
    "mutes": ("guance_mute", "mute", "name"),
}


def render(document, target):
    model = build_model(document)
    env = Environment(undefined=StrictUndefined, keep_trailing_newline=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["hcl_body"] = hcl_body
    groups = [(KIND_TYPES[kind][0], model[kind]) for kind in KIND_TYPES if model[kind]]
    content = env.from_string((ROOT / "templates/resources.tf.j2").read_text()).render(cmdb_groups=groups, **model)
    for name in STATIC_TEMPLATES:
        (target / name).write_text((ROOT / "templates" / name).read_text())
    (target / "generated_resources.tf").write_text(content)
    config = document["global"]
    tfvars = {"guance_endpoint": config["endpoint"], "guance_region": config["region"]}
    (target / "terraform.auto.tfvars.json").write_text(json.dumps(tfvars, indent=2) + "\n")


UUID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{5,63}$")


def render_imports(document, target, existing_path):
    existing = json.loads(Path(existing_path).read_text())
    declared = {entry["id"]: kind for kind in KIND_TYPES for entry in document.get(kind, [])}
    if not isinstance(existing, dict) or not existing or set(existing) - set(declared):
        raise ValueError("existing must be a non-empty object keyed by declared resource ids")
    items = []
    for identifier in sorted(existing):
        if not isinstance(existing[identifier], str) or not UUID_RE.fullmatch(existing[identifier]):
            raise ValueError(f"invalid remote UUID for {identifier}")
        items.append({"address": f"{KIND_TYPES[declared[identifier]][0]}.{identifier}", "uuid": existing[identifier]})
    env = Environment(undefined=StrictUndefined, keep_trailing_newline=True, trim_blocks=True, lstrip_blocks=True)
    content = env.from_string((ROOT / "templates/imports.tf.j2").read_text()).render(imports=items)
    (target / "generated_imports.tf").write_text(content)


def inventory(document, target, outputs_path):
    runtime = json.loads(Path(outputs_path).read_text())["cmdb_runtime"]["value"]
    declared = {entry["id"]: (kind, entry) for kind in KIND_TYPES for entry in document.get(kind, [])}
    if set(runtime) != set(declared):
        raise ValueError("runtime resources do not match manifest")
    records = []
    for identifier in sorted(declared):
        kind, entry = declared[identifier]
        fact = runtime[identifier]
        if not fact.get("uuid") or not fact.get("workspace_uuid"):
            raise ValueError("missing remote UUID")
        records.append(
            {
                "id": identifier,
                "name": entry[KIND_TYPES[kind][2]],
                "type": KIND_TYPES[kind][1],
                "environment": document["global"]["environment"],
                "workspace_alias": document["global"]["workspace_alias"],
                "uuid": fact["uuid"],
                "workspace_uuid": fact["workspace_uuid"],
            }
        )
    (target / "cmdb.json").write_text(json.dumps({"resources": records}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["render", "inventory", "import", "state-key"])
    parser.add_argument("--resources", required=True)
    parser.add_argument("--workdir", help="Terraform working directory (render, inventory)")
    parser.add_argument("--outputs", help="terraform output -json file for inventory")
    parser.add_argument("--existing", help="JSON file {resource id: remote uuid} for the import command")
    parser.add_argument("--project", help="state key project; defaults to global.project in the manifest")
    args = parser.parse_args()
    document = load_manifest(args.resources)
    if args.command == "state-key":
        config = document["global"]
        project = args.project or config.get("project")
        if not project:
            parser.error("state-key requires --project or global.project")
        print(canonical_state_key(environment=config["environment"], project=project, account=config["workspace_alias"]))
        return
    if not args.workdir:
        parser.error(f"{args.command} requires --workdir")
    target = Path(args.workdir)
    target.mkdir(parents=True, exist_ok=True)
    if args.command == "render":
        render(document, target)
    elif args.command == "import":
        if not args.existing:
            parser.error("import requires --existing")
        render_imports(document, target, args.existing)
    else:
        if not args.outputs:
            parser.error("inventory requires --outputs")
        inventory(document, target, args.outputs)


if __name__ == "__main__":
    main()
