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
# scripts/ -> aws-cloud 根
AWS_CLOUD_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
TEMPLATE_DIR = os.path.join(AWS_CLOUD_ROOT, "templates")

DEFAULT_RESOURCES = os.path.join(
    AWS_CLOUD_ROOT, "config", "resources", "ai-workspace-hosts.yaml"
)
DEFAULT_WORKDIR = os.path.join(AWS_CLOUD_ROOT, "envs", "ai-workspace")

# render 时从 templates/ 拷入运行目录的静态文件（使 workdir 成为独立根模块）。
COPY_INTO_WORKDIR = ["provider.tf", "variables.tf", "cloud-init.yaml"]

# 逐主机可选字段的缺省值（集中定义，避免散落的硬编码字面量）。
DEFAULT_PLAN = "vc2-4c-8gb"
DEFAULT_ANSIBLE_USER = "root"

# Operator-facing identity is deliberately separate from the Terraform
# resource name and public FQDN.  Resource names remain state-compatible while
# CMDB/inventory consumers get short, unambiguous node labels.
NODE_METADATA_DEFAULTS = {
    "node_id": "",
    "short_hostname": "",
    "display_name": "",
    "cloud_provider": "aws",
    "cloud_region": "",
    "location": "",
    "node_label": "",
}
VALID_AWS_PROVIDER_ALIASES = {"default", "us", "hk"}


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


# 资源声明里的主机名与服务域名都由 TARGET_DOMAIN_BASE 拼接。Jinja 默认的
# Undefined 会把缺失变量渲染成空串, 于是 console-nat.{{...}} 变成 "console-nat."
# —— 一个看起来像成功、实际错误的主机名。这里显式要求它必须存在。
REQUIRED_TEMPLATE_ENV = ("TARGET_DOMAIN_BASE", "SSH_PUBLIC_DEPLOY_KEY")


def _assert_required_env(content, path):
    missing = [
        k for k in REQUIRED_TEMPLATE_ENV
        if k in content and not os.environ.get(k)
    ]
    if missing:
        raise SystemExit(
            f"{path}: required template variable(s) not set: {', '.join(missing)}. "
            "Hostnames and service domains are composed from them; rendering "
            "without a value would silently produce a truncated domain."
        )


def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    _assert_required_env(content, path)
    from jinja2 import Template
    rendered = Template(content).render(env=os.environ)
    return yaml.safe_load(rendered) or {}


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

    invalid_aliases = sorted(
        {
            str(host.get("aws_provider", "default"))
            for host in hosts
            if str(host.get("aws_provider", "default")) not in VALID_AWS_PROVIDER_ALIASES
        }
    )
    if invalid_aliases:
        raise SystemExit(
            "Unsupported aws_provider alias(es): "
            + ", ".join(invalid_aliases)
            + ". Supported aliases: default, us, hk."
        )

    rendered = (
        _jinja()
        .get_template("hosts.tf.j2")
        .render(
            ssh_keys=ssh_keys,
            hosts=hosts,
            max_host_name_len=max((len(str(host["name"])) for host in hosts), default=0),
            true=True,
            false=False,
        )
    )
    with open(os.path.join(workdir, "generated_hosts.tf"), "w", encoding="utf-8") as fh:
        fh.write(rendered)

    rendered_backend = (
        _jinja()
        .get_template("backend.tf.j2")
        .render(env=os.environ)
    )
    with open(os.path.join(workdir, "backend.tf"), "w", encoding="utf-8") as fh:
        fh.write(rendered_backend)

    # 共享 provider/variables/cloud-init 拷入运行目录，使 workdir 成为可独立
    # terraform 的根模块（这些是渲染产物，已在 env/.gitignore 忽略）。
    for name in COPY_INTO_WORKDIR:
        shutil.copyfile(os.path.join(TEMPLATE_DIR, name), os.path.join(workdir, name))

    tfvars = {
        "region": glob.get("region", "nrt"),
        "aws_region": glob.get("aws_region", "ap-northeast-1"),
        "aws_us_region": glob.get("aws_us_region", "us-east-1"),
        "aws_hk_region": glob.get("aws_hk_region", "ap-east-1"),
        "name_prefix": glob.get("name_prefix", "ai-workspace"),
        "user_data_file": glob.get("user_data_file", "cloud-init.yaml"),
    }
    with open(
        os.path.join(workdir, "terraform.auto.tfvars.json"), "w", encoding="utf-8"
    ) as fh:
        json.dump(tfvars, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"  resources: {os.path.relpath(resources, AWS_CLOUD_ROOT)}")
    print(f"  workdir:   {os.path.relpath(workdir, AWS_CLOUD_ROOT)}")
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
    default_aws_region = glob.get("aws_region", "ap-northeast-1")

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
        host_vars.setdefault(
            "region", host.get("aws_region") or host.get("region") or default_aws_region
        )
        for key, default in NODE_METADATA_DEFAULTS.items():
            value = host.get(key, default)
            if key == "node_id" and not value:
                value = name
            if key == "short_hostname" and not value:
                value = host_vars["node_id"]
            if key == "display_name" and not value:
                value = host_vars["short_hostname"]
            if key == "cloud_region" and not value:
                value = host.get("aws_region") or default_aws_region
            # These fields are canonical resource metadata.  Assign rather
            # than setdefault so an old host_vars entry cannot shadow the
            # current node declaration.
            host_vars[key] = value
        host_vars["billing_mode"] = host.get("billing_mode", "on_demand")
        host_vars["spot_instance"] = host.get("spot_instance", False)
        host_vars["max_runtime_minutes"] = host.get("max_runtime_minutes", 0)
        host_vars["ansible_port"] = host.get("ssh_port", 22)

        # inventory_hostname = service_domains 的首个 FQDN（动态取自资源声明 yaml）；
        # 无 service_domains 时回退到 name。CMDB / inventory / 分组均以此为键。
        sd_raw = host_vars.get("service_domains") or ""
        sd = sd_raw if isinstance(sd_raw, list) else sd_raw.split(",")
        fqdn = next((str(d).strip() for d in sd if str(d).strip()), "") or name

        cmdb[fqdn] = {
            "name": name,
            "fqdn": fqdn,
            "ip": rt.get("ip"),
            "instance_id": rt.get("instance_id"),
            "os_id": rt.get("os_id"),
            "os_name": host.get("os_name", ""),
            "plan": host.get("plan", DEFAULT_PLAN),
            "region": host.get("aws_region") or host.get("region") or default_aws_region,
            "node_id": host_vars["node_id"],
            "short_hostname": host_vars["short_hostname"],
            "display_name": host_vars["display_name"],
            "cloud_provider": host_vars["cloud_provider"],
            "cloud_region": host_vars["cloud_region"],
            "location": host_vars["location"],
            "node_label": host_vars["node_label"],
            "billing_mode": host_vars["billing_mode"],
            "spot_instance": host_vars["spot_instance"],
            "max_runtime_minutes": host_vars["max_runtime_minutes"],
            "ansible_user": host.get("ansible_user", DEFAULT_ANSIBLE_USER),
            "ansible_port": host.get("ssh_port", 22),
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

    rel = os.path.relpath(workdir, AWS_CLOUD_ROOT)
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
