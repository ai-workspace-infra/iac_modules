#!/usr/bin/env python3
"""GitOps ClientMirrorStack YAML -> flat Terraform HCL + Vault KV auto-wiring."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from jinja2 import Environment, FileSystemLoader
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
CLIENT_MIRRORS_ROOT = SCRIPT_DIR.parent
TEMPLATE_DIR = CLIENT_MIRRORS_ROOT / "templates"
DEFAULT_WORKDIR = CLIENT_MIRRORS_ROOT / "envs" / "svc-plus-prod"

COPY_INTO_WORKDIR = ("backend.tf", "provider.tf", "variables.tf")
TF_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
COMPONENT_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
FORBIDDEN_ACCOUNT_ALIASES = frozenset({"primary", "default", "main"})
FORBIDDEN_NAMESPACES = frozenset({"selfhost", "all", "default", "shared"})

ALLOWED_R2_LOCATIONS = frozenset({"apac", "eeur", "enam", "weur", "wnam", "oc"})
ALLOWED_MIN_TLS = frozenset({"1.0", "1.1", "1.2", "1.3"})
ALLOWED_OSS_ACL = frozenset({"public-read", "private"})
ALLOWED_CDN_TYPES = frozenset({"download", "web", "video"})
ALLOWED_CDN_SCOPES = frozenset({"overseas", "domestic", "global"})
ALLOWED_METHODS = frozenset({"GET", "HEAD", "PUT", "POST", "DELETE"})

SENSITIVE_KEY_NAMES = frozenset(
    {
        "access_key_id",
        "access_key_secret",
        "access_token",
        "api_key",
        "api_token",
        "apikey",
        "authorization",
        "password",
        "private_key",
        "secret",
        "secret_access_key",
        "token",
    }
)

SECRET_VALUE_PATTERNS = (
    ("vault-token", re.compile(r"\bhv[sbr]\.[A-Za-z0-9_-]{20,}")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("access-key", re.compile(r"\b(?:AKIA|ASIA|LTAI)[A-Za-z0-9]{12,}\b")),
)

HCL_FORBIDDEN_RULES = (
    ("for_each", re.compile(r"^\s*for_each\s*=", re.M)),
    ("count", re.compile(r"^\s*count\s*=", re.M)),
    ("dynamic", re.compile(r'^\s*dynamic\s+"', re.M)),
    ("templatefile", re.compile(r"\btemplatefile\s*\(")),
    ("template-control", re.compile(r"%\{~?\s*(for|if)\b")),
)


def _scan_forbidden_keys(obj, path="$"):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_str = str(k)
            if key_str.lower() in SENSITIVE_KEY_NAMES:
                hits.append(f"{path}.{key_str}")
            hits.extend(_scan_forbidden_keys(v, f"{path}.{key_str}"))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            hits.extend(_scan_forbidden_keys(item, f"{path}[{idx}]"))
    return hits


def _scan_secret_patterns(raw_text):
    return sorted(name for name, pat in SECRET_VALUE_PATTERNS if pat.search(raw_text))


def _require_non_empty_str(mapping, key, ctx):
    val = mapping.get(key)
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"{ctx}.{key} must be a non-empty string")
    return val.strip()


def _require_tf_id(raw_id, ctx):
    val = str(raw_id or "").strip()
    if not TF_ID_RE.fullmatch(val):
        raise ValueError(f"{ctx} must match {TF_ID_RE.pattern}, got {raw_id!r}")
    return val


def _require_https_origins(origins, ctx):
    if not isinstance(origins, list) or not origins:
        raise ValueError(f"{ctx} must be a non-empty list of HTTPS origins")
    cleaned = []
    for origin in origins:
        s = str(origin or "").strip()
        if not s.startswith("https://"):
            raise ValueError(f"{ctx} entries must use https://, got {origin!r}")
        cleaned.append(s)
    return cleaned


def _require_methods(methods, ctx):
    if not isinstance(methods, list) or not methods:
        raise ValueError(f"{ctx} must be a non-empty list of HTTP methods")
    cleaned = [str(m).strip().upper() for m in methods]
    invalid = set(cleaned) - ALLOWED_METHODS
    if invalid:
        raise ValueError(f"{ctx} has unsupported method(s): {sorted(invalid)}")
    return cleaned


def load_and_validate_manifest(resources_path):
    path = Path(resources_path)
    raw_text = path.read_text(encoding="utf-8")
    pattern_hits = _scan_secret_patterns(raw_text)
    if pattern_hits:
        raise ValueError(f"{path}: credential-shaped content detected: {', '.join(pattern_hits)}")

    doc = yaml.safe_load(raw_text)
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: root document must be a YAML mapping")
    if doc.get("apiVersion") != "gitops.svc.plus/v1alpha1" or doc.get("kind") != "ClientMirrorStack":
        raise ValueError(f"{path}: expected apiVersion=gitops.svc.plus/v1alpha1 kind=ClientMirrorStack")

    key_hits = _scan_forbidden_keys(doc)
    if key_hits:
        raise ValueError(f"{path}: forbidden secret-like YAML key(s): {', '.join(key_hits)}")

    spec = doc.get("spec") or {}
    if not isinstance(spec, dict):
        raise ValueError(f"{path}: spec must be a mapping")

    glob = spec.get("global") or {}
    zone_name = _require_non_empty_str(glob, "zone_name", "spec.global")
    state_cfg = glob.get("state") or {}
    if not isinstance(state_cfg, dict):
        raise ValueError("spec.global.state must be a mapping")
    state_key = canonical_state_key(
        environment=_require_non_empty_str(state_cfg, "environment", "spec.global.state"),
        project=_require_non_empty_str(state_cfg, "project", "spec.global.state"),
        account=_require_non_empty_str(state_cfg, "account", "spec.global.state"),
        namespace=_require_non_empty_str(state_cfg, "namespace", "spec.global.state"),
    )

    products = spec.get("products") or []
    if not isinstance(products, list) or not products:
        raise ValueError("spec.products must be a non-empty list")
    normalized_products = []
    for prod in products:
        if not isinstance(prod, dict):
            raise ValueError("spec.products items must be mappings")
        slug = _require_non_empty_str(prod, "slug", "spec.products[]")
        prefixes = prod.get("prefixes") or []
        if not isinstance(prefixes, list) or not prefixes:
            raise ValueError(f"spec.products[{slug}].prefixes must be a non-empty list")
        normalized_products.append({"slug": slug, "prefixes": [str(p).strip() for p in prefixes]})

    r2_raw = spec.get("cloudflare_r2") or {}
    r2_location = _require_non_empty_str(r2_raw, "location", "spec.cloudflare_r2").lower()
    if r2_location not in ALLOWED_R2_LOCATIONS:
        raise ValueError(f"cloudflare_r2.location must be one of {sorted(ALLOWED_R2_LOCATIONS)}")
    min_tls = str(r2_raw.get("min_tls", "1.2")).strip()
    if min_tls not in ALLOWED_MIN_TLS:
        raise ValueError(f"cloudflare_r2.min_tls must be one of {sorted(ALLOWED_MIN_TLS)}")

    r2 = {
        "module_id": _require_tf_id(r2_raw.get("id", "global_r2"), "spec.cloudflare_r2.id"),
        "bucket_name": _require_non_empty_str(r2_raw, "bucket_name", "spec.cloudflare_r2"),
        "custom_domain": _require_non_empty_str(r2_raw, "custom_domain", "spec.cloudflare_r2"),
        "location": r2_location,
        "min_tls": min_tls,
        "cors_allowed_origins": _require_https_origins(
            r2_raw.get("cors_allowed_origins"), "spec.cloudflare_r2.cors_allowed_origins"
        ),
        "cors_allowed_methods": _require_methods(
            r2_raw.get("cors_allowed_methods"), "spec.cloudflare_r2.cors_allowed_methods"
        ),
        "cors_max_age_seconds": int(r2_raw.get("cors_max_age_seconds", 3600)),
        "token_name": _require_non_empty_str(r2_raw, "token_name", "spec.cloudflare_r2"),
        "vault_kv_path": _require_non_empty_str(r2_raw, "vault_kv_path", "spec.cloudflare_r2").lstrip("/"),
    }

    ali_raw = spec.get("aliyun_oss_cdn") or {}
    oss_region = _require_non_empty_str(ali_raw, "oss_region", "spec.aliyun_oss_cdn")
    if oss_region.startswith("oss-"):
        raise ValueError("aliyun_oss_cdn.oss_region must omit 'oss-' prefix (e.g. cn-hongkong)")
    oss_acl = _require_non_empty_str(ali_raw, "oss_acl", "spec.aliyun_oss_cdn")
    if oss_acl not in ALLOWED_OSS_ACL:
        raise ValueError(f"aliyun_oss_cdn.oss_acl must be one of {sorted(ALLOWED_OSS_ACL)}")
    cdn_type = _require_non_empty_str(ali_raw, "cdn_type", "spec.aliyun_oss_cdn")
    if cdn_type not in ALLOWED_CDN_TYPES:
        raise ValueError(f"aliyun_oss_cdn.cdn_type must be one of {sorted(ALLOWED_CDN_TYPES)}")
    cdn_scope = _require_non_empty_str(ali_raw, "cdn_scope", "spec.aliyun_oss_cdn")
    if cdn_scope not in ALLOWED_CDN_SCOPES:
        raise ValueError(f"aliyun_oss_cdn.cdn_scope must be one of {sorted(ALLOWED_CDN_SCOPES)}")

    ali = {
        "module_id": _require_tf_id(ali_raw.get("id", "cn_oss_cdn"), "spec.aliyun_oss_cdn.id"),
        "bucket_name": _require_non_empty_str(ali_raw, "bucket_name", "spec.aliyun_oss_cdn"),
        "oss_region": oss_region,
        "oss_acl": oss_acl,
        "cdn_domain": _require_non_empty_str(ali_raw, "cdn_domain", "spec.aliyun_oss_cdn"),
        "cdn_type": cdn_type,
        "cdn_scope": cdn_scope,
        "cdn_rate_limit": _require_non_empty_str(ali_raw, "cdn_rate_limit", "spec.aliyun_oss_cdn"),
        "cdn_rate_limit_after": _require_non_empty_str(ali_raw, "cdn_rate_limit_after", "spec.aliyun_oss_cdn"),
        "cdn_bandwidth_alarm_bps": int(ali_raw.get("cdn_bandwidth_alarm_bps", 500000000)),
        "cdn_alarm_contact_group": str(ali_raw.get("cdn_alarm_contact_group", "") or "").strip(),
        "cdn_cas_cert_id": str(ali_raw.get("cdn_cas_cert_id", "") or "").strip(),
        "cors_allowed_origins": _require_https_origins(
            ali_raw.get("cors_allowed_origins"), "spec.aliyun_oss_cdn.cors_allowed_origins"
        ),
        "cors_allowed_methods": _require_methods(
            ali_raw.get("cors_allowed_methods"), "spec.aliyun_oss_cdn.cors_allowed_methods"
        ),
        "cors_max_age_seconds": int(ali_raw.get("cors_max_age_seconds", 3600)),
        "ram_user_name": _require_non_empty_str(ali_raw, "ram_user_name", "spec.aliyun_oss_cdn"),
        "ram_policy_name": _require_non_empty_str(ali_raw, "ram_policy_name", "spec.aliyun_oss_cdn"),
        "vault_kv_path": _require_non_empty_str(ali_raw, "vault_kv_path", "spec.aliyun_oss_cdn").lstrip("/"),
    }

    return {
        "metadata": doc.get("metadata") or {},
        "zone_name": zone_name,
        "state_key": state_key,
        "products": normalized_products,
        "r2": r2,
        "ali": ali,
    }


def _component(name, value):
    cleaned = str(value or "").strip().lower()
    if not COMPONENT_RE.fullmatch(cleaned):
        raise ValueError(f"{name} must match {COMPONENT_RE.pattern}: {value!r}")
    return cleaned


def canonical_state_key(*, environment, project, account, namespace="mirrors"):
    env = _component("environment", environment)
    proj = _component("project", project)
    acct = _component("account", account)
    ns = _component("namespace", namespace)
    if acct in FORBIDDEN_ACCOUNT_ALIASES:
        raise ValueError(f"state account must be concrete, not {acct!r}")
    if ns in FORBIDDEN_NAMESPACES:
        raise ValueError(f"shared state namespace is forbidden: {ns!r}")
    return f"terraform/{env}/{proj}/client-mirrors/{acct}/{ns}/terraform.tfstate"


def find_hcl_violations(text):
    return [name for name, pat in HCL_FORBIDDEN_RULES if pat.search(text)]


def check_hcl_tree(root):
    root_path = Path(root)
    violations = []
    files = sorted([*root_path.rglob("*.tf"), *root_path.rglob("*.tf.j2")])
    for path in files:
        if ".terraform" in path.parts:
            continue
        for rule in find_hcl_violations(path.read_text(encoding="utf-8")):
            violations.append((str(path), rule))
    return violations


def cmd_render(args):
    manifest = load_and_validate_manifest(args.resources)
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    for fname in COPY_INTO_WORKDIR:
        shutil.copyfile(TEMPLATE_DIR / fname, workdir / fname)

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), keep_trailing_newline=True)
    tmpl = env.get_template("mirrors.tf.j2")
    rendered_tf = tmpl.render(
        products=manifest["products"],
        r2=manifest["r2"],
        ali=manifest["ali"],
    )
    violations = find_hcl_violations(rendered_tf)
    if violations:
        raise RuntimeError(f"Rendered HCL violates policy: {violations}")
    (workdir / "generated_mirrors.tf").write_text(rendered_tf, encoding="utf-8")

    tfvars = {
        "zone_name": manifest["zone_name"],
        "alicloud_region": manifest["ali"]["oss_region"],
    }
    (workdir / "terraform.auto.tfvars.json").write_text(
        json.dumps(tfvars, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    summary = {
        "zone_name": manifest["zone_name"],
        "state_key": manifest["state_key"],
        "products": manifest["products"],
        "cloudflare_r2": {
            "bucket": manifest["r2"]["bucket_name"],
            "custom_domain": manifest["r2"]["custom_domain"],
            "location": manifest["r2"]["location"],
            "vault_kv_path": manifest["r2"]["vault_kv_path"],
        },
        "aliyun_oss_cdn": {
            "bucket": manifest["ali"]["bucket_name"],
            "oss_region": manifest["ali"]["oss_region"],
            "oss_acl": manifest["ali"]["oss_acl"],
            "cdn_domain": manifest["ali"]["cdn_domain"],
            "cdn_scope": manifest["ali"]["cdn_scope"],
            "vault_kv_path": manifest["ali"]["vault_kv_path"],
        },
    }
    (workdir / "rendered_manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Rendered dual-mirror Terraform workspace in {workdir}")
    print(f"State key: {manifest['state_key']}")
    return 0


def cmd_state_key(args):
    manifest = load_and_validate_manifest(args.resources)
    print(manifest["state_key"])
    return 0


def cmd_check_hcl(args):
    violations = check_hcl_tree(args.root)
    for path, rule in violations:
        print(f"{path}: forbidden HCL construct ({rule})", file=sys.stderr)
    if violations:
        return 1
    print(f"check-hcl OK: no forbidden HCL constructs under {args.root}")
    return 0


def _unwrap_tf_outputs(raw_obj):
    if "mirror_credentials" in raw_obj:
        node = raw_obj["mirror_credentials"]
        if isinstance(node, dict) and "value" in node:
            return node["value"]
        return node
    return raw_obj


def _scrub_secrets(text, secrets):
    cleaned = text
    for s in secrets:
        if s and len(s) >= 6:
            cleaned = cleaned.replace(s, "[REDACTED]")
    return cleaned


def _validate_kv_payload(name, record):
    if not isinstance(record, dict):
        raise ValueError(f"mirror_credentials.{name} must be a mapping")
    kv_path = str(record.get("vault_kv_path") or "").strip().lstrip("/")
    if not kv_path.startswith("prod/platform/storage/"):
        raise ValueError(f"unexpected vault_kv_path for {name}: {kv_path!r}")
    data = record.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"mirror_credentials.{name}.data must be a mapping")

    required_by_target = {
        "cloudflare_r2": ("access_key_id", "secret_access_key", "bucket", "endpoint", "custom_domain"),
        "aliyun_oss": ("access_key_id", "access_key_secret", "bucket", "endpoint", "cdn_domain", "oss_region", "cdn_scope"),
    }
    for field in required_by_target[name]:
        val = str(data.get(field) or "").strip()
        if not val:
            raise ValueError(f"mirror_credentials.{name}.data.{field} is empty")
    return kv_path, {k: str(v) for k, v in data.items()}


def cmd_vault_sync(args):
    if args.tf_output_json:
        raw_obj = json.loads(Path(args.tf_output_json).read_text(encoding="utf-8"))
    else:
        proc = subprocess.run(
            [args.terraform_bin, f"-chdir={args.workdir}", "output", "-json", "mirror_credentials"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"terraform output failed: {proc.stderr.strip()}")
        raw_obj = json.loads(proc.stdout)

    creds = _unwrap_tf_outputs(raw_obj)
    targets = []
    secret_values = []
    for name in ("cloudflare_r2", "aliyun_oss"):
        kv_path, payload = _validate_kv_payload(name, creds.get(name))
        targets.append((name, kv_path, payload))
        for secret_key in ("access_key_id", "secret_access_key", "access_key_secret"):
            if payload.get(secret_key):
                secret_values.append(payload[secret_key])

    for name, kv_path, payload in targets:
        field_list = ", ".join(sorted(payload.keys()))
        if args.dry_run:
            print(f"[DRY-RUN] Would write {args.vault_mount}/{kv_path} fields=[{field_list}]")
            continue
        cmd = [args.vault_bin, "kv", "put", f"-mount={args.vault_mount}", kv_path, "-"]
        proc = subprocess.run(
            cmd,
            input=json.dumps(payload),
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            safe_err = _scrub_secrets(proc.stderr or "", secret_values)
            raise RuntimeError(f"vault kv put failed for {args.vault_mount}/{kv_path}: {safe_err.strip()}")
        print(f"Synced {args.vault_mount}/{kv_path} fields=[{field_list}] ({name})")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_render = sub.add_parser("render", help="Render Terraform HCL and tfvars from mirrors.yaml")
    p_render.add_argument("--resources", required=True, help="Path to gitops mirrors.yaml")
    p_render.add_argument("--workdir", default=str(DEFAULT_WORKDIR), help="Terraform root workdir")
    p_render.set_defaults(func=cmd_render)

    p_state = sub.add_parser("state-key", help="Print canonical S3 remote state key")
    p_state.add_argument("--resources", required=True, help="Path to gitops mirrors.yaml")
    p_state.set_defaults(func=cmd_state_key)

    p_hcl = sub.add_parser("check-hcl", help="Verify no forbidden HCL loops/dynamic blocks exist")
    p_hcl.add_argument("--root", default=str(CLIENT_MIRRORS_ROOT), help="Directory tree to scan")
    p_hcl.set_defaults(func=cmd_check_hcl)

    p_sync = sub.add_parser("vault-sync", help="Write Terraform storage outputs to Vault KV v2")
    p_sync.add_argument("--workdir", default=str(DEFAULT_WORKDIR), help="Terraform root workdir")
    p_sync.add_argument("--tf-output-json", help="Optional JSON file overriding terraform output -json")
    p_sync.add_argument("--vault-mount", default="kv", help="Vault KV v2 mount name")
    p_sync.add_argument("--vault-bin", default=os.environ.get("VAULT_BIN", "vault"), help="Vault CLI path")
    p_sync.add_argument("--terraform-bin", default=os.environ.get("TERRAFORM", "terraform"), help="Terraform CLI path")
    p_sync.add_argument("--dry-run", action="store_true", help="Validate without writing to Vault")
    p_sync.set_defaults(func=cmd_vault_sync)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
