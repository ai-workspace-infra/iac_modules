#!/usr/bin/env python3
"""Render a Supabase YAML declaration into a Terraform work directory."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

import yaml
from jinja2 import Template


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_FILES = ["provider.tf", "variables.tf", "main.tf", "outputs.tf"]
GITOPS_ROOT = Path(os.environ.get("GITOPS_ROOT", ROOT.parents[2] / "gitops"))
DEFAULT_RESOURCES = GITOPS_ROOT / "resources" / "svc.plus" / "dev" / "supabase" / "supabase.yaml"
DEFAULT_WORKDIR = ROOT / "envs" / "dev"


def load_declaration(path: Path) -> dict:
    rendered = Template(path.read_text(encoding="utf-8")).render(env=os.environ)
    data = yaml.safe_load(rendered) or {}
    global_config = data.get("global") or {}
    database = data.get("database") or {}

    required = {
        "global.organization_id": global_config.get("organization_id"),
        "global.project_name": global_config.get("project_name"),
        "global.region": global_config.get("region"),
        "database.username": database.get("username"),
        "database.name": database.get("name"),
    }
    missing = [name for name, value in required.items() if not str(value or "").strip()]
    if missing:
        raise SystemExit(
            f"{path}: missing required declaration value(s): {', '.join(missing)}. "
            "Use environment variables for organization_id and optionally project_ref."
        )

    return {"global": global_config, "database": database}


def render(args: argparse.Namespace) -> None:
    resources = Path(args.resources).expanduser().resolve()
    workdir = Path(args.workdir).expanduser().resolve()
    data = load_declaration(resources)
    global_config = data["global"]
    database = data["database"]

    workdir.mkdir(parents=True, exist_ok=True)
    for filename in TEMPLATE_FILES:
        shutil.copyfile(ROOT / filename, workdir / filename)

    project_ref = str(global_config.get("project_ref") or "").strip()
    tfvars = {
        "project_ref": project_ref,
        "organization_id": str(global_config["organization_id"]).strip(),
        "project_name": str(global_config["project_name"]).strip(),
        "region": str(global_config["region"]).strip(),
        "instance_size": global_config.get("instance_size"),
        "database_username": str(database["username"]).strip(),
        "database_name": str(database["name"]).strip(),
        "pooler_mode": str(global_config.get("pooler_mode", "session")).strip(),
    }
    (workdir / "terraform.auto.tfvars.json").write_text(
        json.dumps(tfvars, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    import_file = workdir / "import.tf"
    if project_ref:
        import_file.write_text(
            "import {\n"
            "  to = supabase_project.this\n"
            f'  id = "{project_ref}"\n'
            "}\n",
            encoding="utf-8",
        )
    elif import_file.exists():
        import_file.unlink()

    uri_env = database.get("uri_env", "SUPABASE_DATABASE_DIRECT_URL")
    print(f"resources: {resources}")
    print(f"workdir:   {workdir}")
    print(f"wrote:     {', '.join(TEMPLATE_FILES)}, terraform.auto.tfvars.json")
    if project_ref:
        print(f"wrote:     import.tf (project {project_ref})")
    print(
        "database URI: inject TF_VAR_database_uri when using the direct URI; "
        f"declaration hint: {uri_env}"
    )


def print_uri_env(args: argparse.Namespace) -> None:
    resources = Path(args.resources).expanduser().resolve()
    data = load_declaration(resources)
    print(data["database"].get("uri_env", "SUPABASE_DATABASE_DIRECT_URL"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    render_parser = subparsers.add_parser("render", help="YAML -> Terraform workdir")
    render_parser.add_argument("--resources", type=Path, default=DEFAULT_RESOURCES)
    render_parser.add_argument("--workdir", type=Path, default=DEFAULT_WORKDIR)
    render_parser.set_defaults(func=render)
    uri_parser = subparsers.add_parser("uri-env", help="print the URI environment variable name")
    uri_parser.add_argument("--resources", type=Path, default=DEFAULT_RESOURCES)
    uri_parser.set_defaults(func=print_uri_env)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except (OSError, yaml.YAMLError) as exc:
        print(f"render failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
