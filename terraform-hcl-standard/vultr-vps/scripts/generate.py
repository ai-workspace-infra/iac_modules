#!/usr/bin/env python3
"""共享渲染器：资源声明 (config/resources) -> Terraform 资源 / Ansible inventory。

分层（本脚本不依赖某个具体 env，可被多套资源声明复用）：
  - 声明:     ../config/resources/<name>-hosts.yaml        （--resources 覆盖）
  - 共享模板: ../templates/{provider.tf, variables.tf, cloud-init.yaml,
                            hosts.tf.j2, inventory.ini.j2}
  - 运行目录: ../envs/<name>/  （--workdir 覆盖；渲染产物 + tfstate 落此，均 gitignore）

设计要点（满足约束）：
  - 不在 HCL 里使用 for_each/count 等控制结构；用 Python + Jinja2 把 YAML
    展开成 generated_hosts.tf 中逐个的显式 module/resource/data 块。
  - YAML 的 global 段渲染成 terraform.auto.tfvars.json，传给 variables.tf。
  - apply 后用 terraform 运行时输出 + YAML 静态字段合并出 cmdb.json，
    再渲染 inventory.ini；二者供 Ansible（含动态 inventory 脚本）消费。

子命令：
  render      YAML + 模板 -> workdir/{generated_hosts.tf, provider.tf,
              variables.tf, cloud-init.yaml, terraform.auto.tfvars.json}
  inventory   terraform output(cmdb_runtime) + YAML -> workdir/{cmdb.json, inventory.ini}
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

import yaml
from jinja2 import Environment, FileSystemLoader

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# scripts/ -> vultr-vps 根
VULTR_VPS_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
TEMPLATE_DIR = os.path.join(VULTR_VPS_ROOT, "templates")

DEFAULT_RESOURCES = os.path.join(
    VULTR_VPS_ROOT, "config", "resources", "ai-workspace-hosts.yaml"
)
DEFAULT_WORKDIR = os.path.join(VULTR_VPS_ROOT, "envs", "ai-workspace")

# render 时从 templates/ 拷入运行目录的静态文件（使 workdir 成为独立根模块）。
COPY_INTO_WORKDIR = ["provider.tf", "variables.tf", "cloud-init.yaml"]

# 逐主机可选字段的缺省值（集中定义，避免散落的硬编码字面量）。
DEFAULT_PLAN = "vc2-4c-8gb"
DEFAULT_ANSIBLE_USER = "root"


def _tf_id(value):
    """把任意名字转成合法的 Terraform 标识符。"""
    return re.sub(r"[^0-9a-zA-Z_]", "_", str(value))


def _jinja():
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        trim_blocks=True,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    env.filters["tf_id"] = _tf_id
    return env


def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _terraform_output(workdir, name):
    out = subprocess.check_output(
        ["terraform", f"-chdir={workdir}", "output", "-json", name],
        stderr=subprocess.PIPE,
    )
    return json.loads(out)


def cmd_render(args):
    resources, workdir = args.resources, args.workdir
    os.makedirs(workdir, exist_ok=True)
    data = load_yaml(resources)
    glob = data.get("global", {}) or {}
    ssh_keys = data.get("ssh_keys", []) or []
    hosts = data.get("hosts", []) or []

    rendered = (
        _jinja()
        .get_template("hosts.tf.j2")
        .render(ssh_keys=ssh_keys, hosts=hosts, true=True, false=False)
    )
    with open(os.path.join(workdir, "generated_hosts.tf"), "w", encoding="utf-8") as fh:
        fh.write(rendered)

    # 共享 provider/variables/cloud-init 拷入运行目录，使 workdir 成为可独立
    # terraform 的根模块（这些是渲染产物，已在 env/.gitignore 忽略）。
    for name in COPY_INTO_WORKDIR:
        shutil.copyfile(os.path.join(TEMPLATE_DIR, name), os.path.join(workdir, name))

    tfvars = {
        "region": glob.get("region", "nrt"),
        "name_prefix": glob.get("name_prefix", "ai-workspace"),
        "user_data_file": glob.get("user_data_file", "cloud-init.yaml"),
    }
    with open(
        os.path.join(workdir, "terraform.auto.tfvars.json"), "w", encoding="utf-8"
    ) as fh:
        json.dump(tfvars, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"  resources: {os.path.relpath(resources, VULTR_VPS_ROOT)}")
    print(f"  workdir:   {os.path.relpath(workdir, VULTR_VPS_ROOT)}")
    print(
        f"  wrote generated_hosts.tf + {', '.join(COPY_INTO_WORKDIR)}"
        " + terraform.auto.tfvars.json"
    )
    print(f"  next: terraform -chdir={workdir} init && terraform -chdir={workdir} apply")


def cmd_inventory(args):
    resources, workdir = args.resources, args.workdir
    data = load_yaml(resources)
    glob = data.get("global", {}) or {}
    hosts = data.get("hosts", []) or []
    default_region = glob.get("region", "nrt")

    try:
        runtime = _terraform_output(workdir, "cmdb_runtime")
    except (OSError, subprocess.CalledProcessError) as exc:
        msg = getattr(exc, "stderr", b"") or b""
        sys.exit(
            f"无法读取 terraform 输出 cmdb_runtime（请先在 {workdir} terraform apply）。\n"
            + msg.decode(errors="replace")
        )

    cmdb = {}
    groups = {}
    for host in hosts:
        name = host["name"]
        rt = runtime.get(name, {})
        host_vars = dict(host.get("host_vars", {}) or {})
        host_vars.setdefault("os_name", host.get("os_name", ""))
        host_vars.setdefault("plan", host.get("plan", DEFAULT_PLAN))
        host_vars.setdefault("region", host.get("region") or default_region)

        # inventory_hostname = service_domains 的首个 FQDN（动态取自资源声明 yaml）；
        # 无 service_domains 时回退到 name。CMDB / inventory / 分组均以此为键。
        sd = (host_vars.get("service_domains") or "").split(",")
        fqdn = next((d.strip() for d in sd if d.strip()), "") or name

        cmdb[fqdn] = {
            "name": name,
            "fqdn": fqdn,
            "ip": rt.get("ip"),
            "instance_id": rt.get("instance_id"),
            "os_id": rt.get("os_id"),
            "os_name": host.get("os_name", ""),
            "plan": host.get("plan", DEFAULT_PLAN),
            "region": host.get("region") or default_region,
            "ansible_user": host.get("ansible_user", DEFAULT_ANSIBLE_USER),
            "groups": host.get("groups", []) or [],
            "tags": host.get("tags", []) or [],
            "host_vars": host_vars,
        }
        for group in cmdb[fqdn]["groups"] or ["ungrouped"]:
            groups.setdefault(group, []).append(fqdn)

    # 非空传递检查：运行时事实(ip/instance_id)必须由 terraform 输出带回，否则下游
    # inventory 会渲染出空 ansible_host、静默连错主机。缺失即抛错中止（默认要求非空）。
    problems = []
    for fqdn, h in cmdb.items():
        if not str(h.get("ip") or "").strip():
            problems.append(f"  - {fqdn} (name={h['name']}): 缺少运行时 ip")
        if not str(h.get("instance_id") or "").strip():
            problems.append(f"  - {fqdn} (name={h['name']}): 缺少 instance_id")
    if problems:
        sys.exit(
            "CMDB 非空校验失败：以下主机缺少 terraform 运行时事实；请确认已在 "
            f"{workdir} 完成 terraform apply 且 output cmdb_runtime 覆盖这些主机：\n"
            + "\n".join(problems)
        )

    with open(os.path.join(workdir, "cmdb.json"), "w", encoding="utf-8") as fh:
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

    rendered = (
        _jinja()
        .get_template("inventory.ini.j2")
        .render(
            cmdb=cmdb,
            lines=lines,
            groups={g: sorted(m) for g, m in sorted(groups.items())},
        )
    )
    with open(os.path.join(workdir, "inventory.ini"), "w", encoding="utf-8") as fh:
        fh.write(rendered)

    rel = os.path.relpath(workdir, VULTR_VPS_ROOT)
    print(f"  wrote {os.path.join(rel, 'cmdb.json')}")
    print(f"  wrote {os.path.join(rel, 'inventory.ini')}")


def _add_common(p):
    p.add_argument("--resources", default=DEFAULT_RESOURCES, help="资源声明 YAML 路径")
    p.add_argument("--workdir", default=DEFAULT_WORKDIR, help="terraform 运行目录")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="YAML+模板 -> workdir 渲染产物")
    r.set_defaults(func=cmd_render)
    _add_common(r)
    i = sub.add_parser(
        "inventory", help="terraform output + YAML -> cmdb.json + inventory.ini"
    )
    i.set_defaults(func=cmd_inventory)
    _add_common(i)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
