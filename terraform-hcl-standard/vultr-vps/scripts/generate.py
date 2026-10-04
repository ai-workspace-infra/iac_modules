#!/usr/bin/env python3
"""共享渲染器：GitOps 资源声明 -> Terraform 资源 / Ansible inventory。

分层（本脚本不依赖某个具体 env，可被多套资源声明复用）：
  - 声明:     ../../gitops/resources/<project>/<env>/<provider>/<name>.yaml        （--resources 覆盖）
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
GITOPS_ROOT = os.environ.get(
    "GITOPS_ROOT", os.path.abspath(os.path.join(VULTR_VPS_ROOT, "..", "..", "gitops"))
)

DEFAULT_RESOURCES = os.path.join(
    GITOPS_ROOT, "resources", "svc.plus", "uat", "vultr", "ai-workspace.yaml"
)
DEFAULT_WORKDIR = os.path.join(VULTR_VPS_ROOT, "envs", "ai-workspace")

# render 时从 templates/ 拷入运行目录的静态文件（使 workdir 成为独立根模块）。
COPY_INTO_WORKDIR = ["provider.tf", "variables.tf", "cloud-init.yaml"]

# 逐主机可选字段的缺省值（集中定义，避免散落的硬编码字面量）。
DEFAULT_PLAN = "vc2-4c-8gb"
DEFAULT_ANSIBLE_USER = "root"
DEFAULT_BACKUPS_SCHEDULE = {"type": "daily", "hour": 5}

# render 阶段就落盘的静态清单：apply 之前即可读，供 destroy 作用域断言与
# 备份计划对账使用（二者都需要“这份 profile 应该有哪些实例”这一事实，而
# cmdb.json 要等 apply 之后才存在）。
MANIFEST_FILE = "hosts_manifest.json"


def _tf_id(value):
    """把任意名字转成合法的 Terraform 标识符。"""
    return re.sub(r"[^0-9a-zA-Z_]", "_", str(value))


def _host_label(host):
    """实例 label：前缀只来自该主机自己那份声明的 global.name_prefix。

    多份资源声明组合成一个 workspace 时（web-saas + agent-proxy），全局
    tfvars 的 name_prefix 只保留最后读到的那份，用它渲染会把别的域的前缀
    安到本主机头上。因此前缀在合并时逐主机记住（_merge_sources 注入
    _name_prefix），此处只做拼接。
    """
    prefix = str(host.get("_name_prefix", "") or "").strip()
    name = host["name"]
    return f"{prefix}-{name}" if prefix else name


def _host_tags(host):
    """实例 tags：同样带上该主机自己的前缀，空前缀不产生空标签。"""
    prefix = str(host.get("_name_prefix", "") or "").strip()
    tags = [str(t) for t in (host.get("tags", []) or []) if str(t).strip()]
    return ([prefix] if prefix else []) + tags


def _merge_sources(resources):
    """按顺序读入多份资源声明并合并。

    global 仍然合并成一份（region/user_data_file 等确实是整个 workspace 的
    属性），但 name_prefix 属于“这份声明里的主机怎么命名”，会逐主机粘在
    host['_name_prefix'] 上，不随后续文件被覆盖。
    """
    merged_glob = {}
    merged_ssh_keys = []
    merged_hosts = []

    for res_path in resources.split(","):
        res_path = res_path.strip()
        if not res_path:
            continue
        data = load_yaml(res_path)
        source_glob = data.get("global", {}) or {}
        merged_glob.update(source_glob)
        for key in data.get("ssh_keys", []) or []:
            if key not in merged_ssh_keys:
                merged_ssh_keys.append(key)
        for host in data.get("hosts", []) or []:
            host = dict(host)
            host["_name_prefix"] = source_glob.get("name_prefix", "") or ""
            host["_source"] = res_path
            host["label"] = _host_label(host)
            host["tf_tags"] = _host_tags(host)
            merged_hosts.append(host)

    return merged_glob, merged_ssh_keys, merged_hosts


def _write_manifest(workdir, hosts):
    """写 hosts_manifest.json：apply 之前就成立的静态事实。"""
    manifest = {
        "hosts": [
            {
                "name": host["name"],
                "label": host["label"],
                "source": host.get("_source", ""),
                "snapshot_id": host.get("snapshot_id", None),
                "backups": bool(host.get("backups", False)),
                "backups_schedule": host.get(
                    "backups_schedule", DEFAULT_BACKUPS_SCHEDULE
                ),
            }
            for host in hosts
        ]
    }
    path = os.path.join(workdir, MANIFEST_FILE)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path


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
REQUIRED_TEMPLATE_ENV = ("TARGET_DOMAIN_BASE",)


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
    workdir = args.workdir
    os.makedirs(workdir, exist_ok=True)
    
    glob, ssh_keys, hosts = _merge_sources(args.resources)

    rendered = (
        _jinja()
        .get_template("hosts.tf.j2")
        .render(ssh_keys=ssh_keys, hosts=hosts, true=True, false=False)
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
        "name_prefix": glob.get("name_prefix", "ai-workspace"),
        "user_data_file": glob.get("user_data_file", "cloud-init.yaml"),
    }
    with open(
        os.path.join(workdir, "terraform.auto.tfvars.json"), "w", encoding="utf-8"
    ) as fh:
        json.dump(tfvars, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    _write_manifest(workdir, hosts)

    print(f"  resources: {args.resources}")
    print(f"  workdir:   {os.path.relpath(workdir, VULTR_VPS_ROOT)}")
    print(
        f"  wrote generated_hosts.tf + {', '.join(COPY_INTO_WORKDIR)}"
        f" + terraform.auto.tfvars.json + {MANIFEST_FILE}"
    )
    print(f"  next: terraform -chdir={workdir} init && terraform -chdir={workdir} apply")


def cmd_inventory(args):
    workdir = args.workdir
    glob, _, hosts = _merge_sources(args.resources)
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
        sd_raw = host_vars.get("service_domains") or ""
        sd = sd_raw if isinstance(sd_raw, list) else sd_raw.split(",")
        fqdn = next((str(d).strip() for d in sd if str(d).strip()), "") or name

        cmdb[fqdn] = {
            "name": name,
            "fqdn": fqdn,
            # 云上实例的真实 label。instance_id 会因重建而失效，label 不会，
            # 是按名反查真实实例（resize preflight 的自愈路径）的稳定锚点。
            "label": host["label"],
            "ip": rt.get("ip"),
            "instance_id": rt.get("instance_id"),
            "os_id": rt.get("os_id"),
            "snapshot_id": host.get("snapshot_id"),
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

    # Web SaaS is intentionally a co-located full-stack host, so its Console,
    # Accounts and PostgreSQL aliases may share one IP.  The safety boundary is
    # between the web_saas role and the separate agent_proxy role: if those two
    # roles share an IP, Ansible can silently deploy the agent role onto the
    # Web SaaS host and DNS reconciliation can publish the wrong address.
    role_ip_owners = {"web_saas": {}, "agent_proxy": {}}
    for fqdn, host in cmdb.items():
        ip = str(host.get("ip") or "").strip()
        if not ip:
            continue
        for role in role_ip_owners:
            if role in (host.get("groups") or []):
                role_ip_owners[role].setdefault(ip, []).append(fqdn)

    cross_role_ips = sorted(
        set(role_ip_owners["web_saas"]) & set(role_ip_owners["agent_proxy"])
    )
    sit_all_in_one = (
        any(
            os.path.basename(os.path.dirname(os.path.normpath(resource))) == "sit"
            and os.path.basename(os.path.normpath(resource)) == "all-in-one.yaml"
            for resource in args.resources.split(",")
        )
    )
    if cross_role_ips and not sit_all_in_one:
        details = [
            f"  - {ip}: web_saas={', '.join(role_ip_owners['web_saas'][ip])}; "
            f"agent_proxy={', '.join(role_ip_owners['agent_proxy'][ip])}"
            for ip in cross_role_ips
        ]
        sys.exit(
            "CMDB role/IP 校验失败：web_saas 与 agent_proxy 共享同一个运行时 IP；"
            "请检查 Terraform workspace/state 与 cmdb_runtime 映射后再部署：\n"
            + "\n".join(details)
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
