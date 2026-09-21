#!/usr/bin/env python3
"""Render Akamai Cloud/Linode GitOps YAML into explicit Terraform and CMDB."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template

from state_contract import UAT_NAMESPACES, validate_namespace

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
GITOPS_ROOT = Path(os.environ.get("GITOPS_ROOT", ROOT.parents[2] / "gitops"))
DEFAULT_RESOURCES = GITOPS_ROOT / "resources" / "svc.plus" / "uat" / "akamai" / "ai-workspace.yaml"
DEFAULT_WORKDIR = ROOT / "envs" / "uat" / "ai-workspace"
COPY_INTO_WORKDIR = ("provider.tf", "variables.tf", "cloud-init.yaml")
LINODE_FIREWALL_LABEL_MAX = 32


def tf_id(value):
    return re.sub(r"[^0-9A-Za-z_]", "_", str(value))


def firewall_label(instance_label):
    """Return a stable Linode firewall label within the provider's 32-char limit."""
    candidate = f"{instance_label}-firewall"
    if len(candidate) <= LINODE_FIREWALL_LABEL_MAX:
        return candidate

    digest = hashlib.sha256(str(instance_label).encode("utf-8")).hexdigest()[:8]
    prefix_length = LINODE_FIREWALL_LABEL_MAX - len(digest) - 1
    return f"{str(instance_label)[:prefix_length]}-{digest}"


def _load_yaml(path: Path):
    content = path.read_text(encoding="utf-8")
    rendered = Template(content).render(env=os.environ)
    return yaml.safe_load(rendered) or {}


def load_sources(resources):
    global_config = {}
    ssh_keys = []
    hosts = []
    for raw_path in str(resources).split(","):
        path = Path(raw_path.strip())
        data = _load_yaml(path)
        source_global = data.get("global", {}) or {}
        global_config.update(source_global)
        for key in data.get("ssh_keys", []) or []:
            if key not in ssh_keys:
                ssh_keys.append(key)
        for raw_host in data.get("hosts", []) or []:
            host = dict(raw_host)
            prefix = str(source_global.get("name_prefix", "") or "").strip()
            name = str(host["name"])
            host["label"] = f"{prefix}-{name}" if prefix else name
            host["firewall_label"] = firewall_label(host["label"])
            host["_source"] = str(path)
            hosts.append(host)
    if not hosts:
        raise SystemExit("至少需要一个 hosts 声明")
    if not ssh_keys:
        raise SystemExit("Akamai Cloud/Linode image 部署至少需要一个 ssh_keys 公钥")
    return global_config, ssh_keys, hosts


def jinja():
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        undefined=StrictUndefined,
        # Keep line boundaries around Jinja control blocks. The generated HCL
        # is intentionally explicit and must remain one argument per line.
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    env.filters["tf_id"] = tf_id
    return env


def write_manifest(workdir: Path, hosts, namespace):
    manifest = {
        "provider": "akamai-cloud",
        "state_namespace": namespace,
        "hosts": [
            {
                "name": host["name"],
                "label": host["label"],
                "source": host.get("_source", ""),
                "region": host.get("region"),
                "type": host.get("type", host.get("plan")),
                "image": host.get("image"),
                "groups": host.get("groups", []),
            }
            for host in hosts
        ],
    }
    (workdir / "hosts_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def render(args):
    resources, workdir = Path(args.resources), Path(args.workdir)
    global_config, ssh_keys, hosts = load_sources(resources)
    declared_environment = str(global_config.get("environment", "")).strip().lower()
    environment = declared_environment
    path_match = re.search(r"/resources/[^/]+/(uat|prod)/akamai/", str(resources))
    if path_match:
        environment = path_match.group(1)
    envs_root = (ROOT / "envs").resolve()
    resolved_workdir = workdir.resolve()
    if resolved_workdir.is_relative_to(envs_root):
        relative_parts = resolved_workdir.relative_to(envs_root).parts
        if relative_parts and relative_parts[0] in {"uat", "prod"}:
            environment = relative_parts[0]

    namespace = getattr(args, "namespace", None) or os.environ.get("TF_STATE_WORKSPACE")
    namespace = namespace or resources.stem
    namespace = validate_namespace(namespace, environment=environment)
    if resolved_workdir.is_relative_to(envs_root) and workdir.name != namespace:
        raise SystemExit(
            f"Akamai workdir must end with /{namespace}; shared {workdir} is forbidden"
        )
    if environment == "uat" and len(hosts) != 1:
        raise SystemExit(
            f"Akamai namespace {namespace} must contain exactly one host; got {len(hosts)}"
        )
    prevent_destroy = environment == "prod" or bool(
        global_config.get("prevent_destroy", False)
    )
    workdir.mkdir(parents=True, exist_ok=True)
    environment = jinja()
    generated = workdir / "generated_hosts.tf"
    generated.write_text(
        environment.get_template("hosts.tf.j2").render(
            ssh_keys=ssh_keys,
            hosts=hosts,
            module_root=os.path.relpath(ROOT / "modules", workdir),
            compute_module="compute_protected" if prevent_destroy else "compute",
            # Account-level linode_sshkey objects cannot be owned by six states.
            # Each isolated namespace therefore passes the public keys directly
            # to its instance unless a legacy declaration explicitly opts in.
            manage_account_ssh_keys=bool(global_config.get("manage_account_ssh_keys", False)),
        ),
        encoding="utf-8",
    )
    subprocess.run(["terraform", "fmt", str(generated)], check=True, stdout=subprocess.DEVNULL)
    (workdir / "backend.tf").write_text(
        environment.get_template("backend.tf.j2").render(env=os.environ),
        encoding="utf-8",
    )
    for name in COPY_INTO_WORKDIR:
        shutil.copyfile(TEMPLATES / name, workdir / name)
    tfvars = {
        "region": global_config.get("region", "us-east"),
        "image": global_config.get("image", "linode/debian12"),
        "type": global_config.get("type", global_config.get("plan", "g6-standard-1")),
        "name_prefix": global_config.get("name_prefix", ""),
        "user_data_file": global_config.get("user_data_file", "cloud-init.yaml"),
    }
    (workdir / "terraform.auto.tfvars.json").write_text(
        json.dumps(tfvars, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_manifest(workdir, hosts, namespace)
    print(f"rendered {resources} -> {workdir}")


def terraform_output(workdir: Path):
    try:
        raw = subprocess.check_output(
            ["terraform", f"-chdir={workdir}", "output", "-json", "cmdb_runtime"],
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or ""
        raise SystemExit(
            f"无法读取 {workdir} 的 cmdb_runtime，请先完成 terraform apply。\n{detail}"
        ) from exc
    return json.loads(raw)


def inventory(args):
    resources, workdir = Path(args.resources), Path(args.workdir)
    global_config, _, hosts = load_sources(resources)
    runtime = terraform_output(workdir)
    cmdb = {}
    groups = {}
    lines = {}
    default_region = global_config.get("region", "us-east")
    for host in hosts:
        name = host["name"]
        facts = runtime.get(name, {})
        host_vars = dict(host.get("host_vars", {}) or {})
        host_vars.setdefault("cloud_provider", "akamai-cloud")
        host_vars.setdefault("cloud_region", host.get("region", default_region))
        host_vars.setdefault("plan", host.get("type", host.get("plan", global_config.get("type"))))
        host_vars.setdefault("image", host.get("image", global_config.get("image")))
        service_domains = host_vars.get("service_domains", []) or []
        fqdn = str(service_domains[0]).strip() if isinstance(service_domains, list) and service_domains else name
        ssh_user = host.get("ansible_user", "root")
        cmdb[fqdn] = {
            "name": name,
            "fqdn": fqdn,
            "label": host["label"],
            "ip": facts.get("ip"),
            "private_ip": facts.get("private_ip"),
            "ipv6": facts.get("ipv6"),
            "instance_id": facts.get("instance_id"),
            "region": host_vars["cloud_region"],
            "type": host_vars["plan"],
            "image": host_vars["image"],
            # Keep deployment metadata at the top level as well as in
            # host_vars. The platform-ops bootstrap router reads groups and
            # the SSH user directly from cmdb.json.
            "groups": list(host.get("groups", []) or []),
            "ansible_user": ssh_user,
            "host_vars": host_vars,
        }
        lines[fqdn] = f"{fqdn} ansible_host={facts.get('ip', '')} ansible_user={ssh_user}"
        for group in host.get("groups", []) or []:
            groups.setdefault(str(group), []).append(fqdn)
    (workdir / "cmdb.json").write_text(
        json.dumps(cmdb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (workdir / "inventory.ini").write_text(
        jinja().get_template("inventory.ini.j2").render(groups=groups, lines=lines),
        encoding="utf-8",
    )
    print(f"wrote {workdir / 'cmdb.json'} and {workdir / 'inventory.ini'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, handler in (("render", render), ("inventory", inventory)):
        sub = subparsers.add_parser(command)
        sub.add_argument("--resources", type=Path, default=DEFAULT_RESOURCES)
        sub.add_argument("--workdir", type=Path, default=DEFAULT_WORKDIR)
        sub.add_argument(
            "--namespace",
            help=(
                "isolated Terraform state namespace; UAT is restricted to: "
                + ", ".join(UAT_NAMESPACES)
            ),
        )
        sub.set_defaults(handler=handler)
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
