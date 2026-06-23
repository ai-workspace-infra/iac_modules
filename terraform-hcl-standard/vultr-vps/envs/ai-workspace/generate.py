#!/usr/bin/env python3
"""hosts.yaml -> Terraform 资源 / Ansible inventory 渲染器。

设计要点（满足约束）：
  - 不在 HCL 里使用 for_each/count 等控制结构；用 Python + Jinja2 把 YAML
    展开成 generated_hosts.tf 中逐个的显式 module/resource/data 块。
  - hosts.yaml 的 global 段渲染成 terraform.auto.tfvars.json，传给 variables.tf。
  - apply 后用 terraform 运行时输出 + YAML 静态字段合并出 cmdb.json，
    再渲染 inventory.ini；二者供 Ansible（含动态 inventory 脚本）消费。

子命令：
  render      hosts.yaml -> generated_hosts.tf + terraform.auto.tfvars.json
  inventory   terraform output(cmdb_runtime) + hosts.yaml -> cmdb.json + inventory.ini
"""

import argparse
import json
import os
import re
import subprocess
import sys

import yaml
from jinja2 import Environment, FileSystemLoader

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTS_YAML = os.path.join(HERE, "hosts.yaml")
TEMPLATE_DIR = os.path.join(HERE, "templates")
GENERATED_TF = os.path.join(HERE, "generated_hosts.tf")
TFVARS_JSON = os.path.join(HERE, "terraform.auto.tfvars.json")
CMDB_JSON = os.path.join(HERE, "cmdb.json")
INVENTORY_INI = os.path.join(HERE, "inventory.ini")


def _tf_id(value):
    """把任意名字转成合法的 Terraform 标识符。"""
    return re.sub(r"[^0-9a-zA-Z_]", "_", str(value))


def _env():
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        trim_blocks=True,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    env.filters["tf_id"] = _tf_id
    return env


def load_yaml():
    with open(HOSTS_YAML, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def cmd_render(_args):
    data = load_yaml()
    glob = data.get("global", {}) or {}
    ssh_keys = data.get("ssh_keys", []) or []
    hosts = data.get("hosts", []) or []

    env = _env()
    rendered = env.get_template("hosts.tf.j2").render(
        ssh_keys=ssh_keys,
        hosts=hosts,
        true=True,
        false=False,
    )
    with open(GENERATED_TF, "w", encoding="utf-8") as fh:
        fh.write(rendered)

    tfvars = {
        "region": glob.get("region", "nrt"),
        "name_prefix": glob.get("name_prefix", "ai-workspace"),
        "user_data_file": glob.get("user_data_file", "cloud-init.yaml"),
    }
    with open(TFVARS_JSON, "w", encoding="utf-8") as fh:
        json.dump(tfvars, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"  wrote {os.path.relpath(GENERATED_TF, HERE)}")
    print(f"  wrote {os.path.relpath(TFVARS_JSON, HERE)}")
    print("  next: terraform init && terraform apply")


def _terraform_output(name):
    out = subprocess.check_output(
        ["terraform", f"-chdir={HERE}", "output", "-json", name],
        stderr=subprocess.PIPE,
    )
    return json.loads(out)


def cmd_inventory(_args):
    data = load_yaml()
    glob = data.get("global", {}) or {}
    hosts = data.get("hosts", []) or []
    default_region = glob.get("region", "nrt")

    try:
        runtime = _terraform_output("cmdb_runtime")
    except (OSError, subprocess.CalledProcessError) as exc:
        msg = getattr(exc, "stderr", b"") or b""
        sys.exit(
            "无法读取 terraform 输出 cmdb_runtime（请先在本目录 terraform apply）。\n"
            + msg.decode(errors="replace")
        )

    cmdb = {}
    groups = {}
    for host in hosts:
        name = host["name"]
        rt = runtime.get(name, {})
        host_vars = dict(host.get("host_vars", {}) or {})
        host_vars.setdefault("os_name", host.get("os_name", ""))
        host_vars.setdefault("plan", host.get("plan", "vc2-4c-8gb"))
        host_vars.setdefault("region", host.get("region") or default_region)

        cmdb[name] = {
            "name": name,
            "ip": rt.get("ip"),
            "instance_id": rt.get("instance_id"),
            "os_id": rt.get("os_id"),
            "os_name": host.get("os_name", ""),
            "plan": host.get("plan", "vc2-4c-8gb"),
            "region": host.get("region") or default_region,
            "ansible_user": host.get("ansible_user", "root"),
            "groups": host.get("groups", []) or [],
            "tags": host.get("tags", []) or [],
            "host_vars": host_vars,
        }
        for group in cmdb[name]["groups"] or ["ungrouped"]:
            groups.setdefault(group, []).append(name)

    with open(CMDB_JSON, "w", encoding="utf-8") as fh:
        json.dump(cmdb, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    # 每台主机整行在 Python 侧拼好（含带引号的 host_vars），模板里只做表达式
    # 输出，避免 Jinja2 trim_blocks 把行尾 block 标签后的换行吃掉。
    lines = {}
    for name, host in cmdb.items():
        parts = [
            name,
            f"ansible_host={host['ip']}",
            f"ansible_user={host['ansible_user']}",
        ]
        for k, v in host["host_vars"].items():
            parts.append(f'{k}="{v}"')
        lines[name] = " ".join(parts)

    env = _env()
    rendered = env.get_template("inventory.ini.j2").render(
        cmdb=cmdb,
        lines=lines,
        groups={g: sorted(m) for g, m in sorted(groups.items())},
    )
    with open(INVENTORY_INI, "w", encoding="utf-8") as fh:
        fh.write(rendered)

    print(f"  wrote {os.path.relpath(CMDB_JSON, HERE)}")
    print(f"  wrote {os.path.relpath(INVENTORY_INI, HERE)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("render", help="YAML -> generated_hosts.tf + tfvars").set_defaults(
        func=cmd_render
    )
    sub.add_parser(
        "inventory", help="terraform output + YAML -> cmdb.json + inventory.ini"
    ).set_defaults(func=cmd_inventory)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
