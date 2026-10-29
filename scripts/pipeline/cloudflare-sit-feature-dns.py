#!/usr/bin/env python3
"""Reconcile one owned Dev feature-lane DNS A record; never mutates onwalk.net aliases."""
from __future__ import annotations

import ipaddress
import datetime
import hashlib
import json
import os
import re
import sys
from urllib.parse import urlencode

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("feature_dns_base", Path(__file__).with_name("cloudflare-gateway-dns-upsert.py"))
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)


def lane_domain(feature_id: str, service: str, zone: str) -> str:
    if not re.fullmatch(r"feature-[a-z][a-z0-9-]{1,48}", feature_id) or feature_id.endswith("-"):
        raise base.OperationError("FEATURE_ID must be a stable lowercase DNS-safe identifier")
    if service not in ("console", "accounts", "billing"):
        raise base.OperationError("unsupported SIT feature service")
    slug = feature_id.removeprefix("feature-")
    normalized_zone = base.domain(zone)
    if normalized_zone != "onwalk.net":
        raise base.OperationError("SIT feature DNS is restricted to the declared onwalk.net zone")
    label = f"{slug}-sit" if service == "console" else f"{service}-{slug}-sit"
    name = f"{label}.{normalized_zone}"
    return base.domain(name)


def tagged_lane_domain(feature_id: str, feature_tag: str, service: str, zone: str) -> str:
    """Derive a v2 hostname; provenance must be verified by the caller first."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,45}", feature_id) or feature_id.endswith('-'):
        raise base.OperationError("invalid Feature ID")
    suffix = '-' + feature_id
    if not isinstance(feature_tag, str) or not feature_tag.endswith(suffix):
        raise base.OperationError("tag does not match Feature ID")
    prefix = feature_tag[:-len(suffix)]
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", prefix):
        raise base.OperationError("invalid feature tag name")
    if service not in ("console", "accounts", "billing") or base.domain(zone) != "onwalk.net":
        raise base.OperationError("unsupported SIT feature service or zone")
    label = feature_tag + '-sit' if service == 'console' else service + '-' + feature_tag + '-sit'
    if len(label) > 63:
        raise base.OperationError("SIT DNS label exceeds 63 characters")
    return base.domain(label + '.onwalk.net')


def verify_domain_contract(path: str) -> None:
    """Validate a reviewed declaration; the caller authenticates its GitOps SHA."""
    import yaml
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 65536:
        raise base.OperationError('missing or oversized GitOps domain declaration')
    try:
        declaration = yaml.safe_load(source.read_text())
    except (yaml.YAMLError, UnicodeError) as exc:
        raise base.OperationError('invalid GitOps domain declaration') from exc
    expected = {'format': 'sit-feature-domain-contract/v2', 'environment': 'sit', 'zone': 'onwalk.net',
                'namespace': 'feature-{feature_id}-sit',
                'services': {'console': '{feature_tag}-sit.onwalk.net',
                             'accounts': 'accounts-{feature_tag}-sit.onwalk.net',
                             'billing': 'billing-{feature_tag}-sit.onwalk.net'}}
    if not isinstance(declaration, dict) or any(declaration.get(k) != v for k, v in expected.items()):
        raise base.OperationError('GitOps domain declaration differs from the approved tagged SIT contract')
    dns = declaration.get('dns')
    if not isinstance(dns, dict) or type(dns.get('proxied')) is not bool or type(dns.get('ttl_seconds')) is not int or any(dns.get(k) != v for k, v in {
            'provider_owner': 'iac_modules', 'record_type': 'A', 'target': 'fresh-cmdb-dev-k3s-v5-ip',
            'ttl_seconds': 60, 'proxied': False, 'conflict_policy': 'refuse-unowned-record',
            'cleanup_policy': 'exact-feature-id-and-tag-owned-records-only'}.items()):
        raise base.OperationError('GitOps DNS owner or target contract differs')


def requested_domain(env: dict, feature_id: str, service: str, zone: str) -> tuple[str, str | None]:
    operation = env.get('RESOURCE_OPERATION', 'sit-feature-dns')
    if operation == 'sit-feature-dns':
        if env.get('FEATURE_TAG') or env.get('FEATURE_HOSTNAME'):
            raise base.OperationError('legacy DNS operation cannot consume tagged inputs')
        return lane_domain(feature_id, service, zone), None
    if operation != 'sit-feature-tag-dns':
        raise base.OperationError('unsupported feature DNS operation')
    verify_domain_contract(base.required(env, 'FEATURE_DOMAIN_CONTRACT'))
    tag = base.required(env, 'FEATURE_TAG')
    hostname = tagged_lane_domain(feature_id, tag, service, zone)
    if base.required(env, 'FEATURE_HOSTNAME') != hostname:
        raise base.OperationError('candidate hostname does not match tag, feature and service')
    return hostname, tag


def dev_ingress_ip(cmdb: dict, node: str) -> str:
    if node != "dev-k3s-v5":
        raise base.OperationError("SIT feature DNS is restricted to the declared Dev ingress node")
    host = cmdb.get(node)
    groups = set(host.get("groups", [])) if isinstance(host, dict) else set()
    if not isinstance(host, dict) or not {"dev", "k3s", "k3s_server", "akamai_cloud"} <= groups:
        raise base.OperationError("CMDB does not identify the declared Dev K3s ingress node")
    try:
        target = ipaddress.IPv4Address(host.get("ip", ""))
    except ipaddress.AddressValueError:
        raise base.OperationError("Dev ingress target must be a valid public IPv4 address") from None
    if not target.is_global:
        raise base.OperationError("Dev ingress target must be a public IPv4 address")
    return str(target)


def verify_current_target(cmdb, target, token):
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import verify_dev_sit_target as target_check
        instance_id = str(cmdb.get('dev-k3s-v5', {}).get('instance_id', ''))
        target_check.validate_cmdb(cmdb, instance_id)
        status, facts = target_check._linode_get_one('linode/instances/' + instance_id, token)
        if status != 200 or target_check.validate(cmdb, facts, instance_id) != target:
            raise base.OperationError('fresh Dev provider target verification failed')
        return {'instance_id': instance_id, 'node': 'dev-k3s-v5', 'ip': target,
                'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    except (ImportError, RuntimeError, ValueError):
        raise base.OperationError('fresh Dev provider target verification failed') from None


def verify_candidate_receipt(path, feature_id, tag, fingerprint, env):
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 1000000:
        raise base.OperationError('same-run candidate receipt unavailable')
    raw = source.read_bytes()
    expected = env.get('FEATURE_CANDIDATE_RECEIPT_SHA256', '')
    if not re.fullmatch(r'[0-9a-f]{64}', expected) or hashlib.sha256(raw).hexdigest() != expected:
        raise base.OperationError('candidate receipt digest mismatch')
    receipt = json.loads(raw)
    if not isinstance(receipt, dict):
        raise base.OperationError('invalid candidate receipt')
    repo = env.get('GITHUB_REPOSITORY', '')
    ref = repo + '/.github/workflows/feature-lane-deploy.yml@refs/heads/main'
    producer = receipt.get('source', {}) if isinstance(receipt, dict) else {}
    lane = receipt.get('projection', {}).get('tagged_lane', {}) if isinstance(receipt, dict) else {}
    if (repo != 'ai-workspace-infra/Platform-Orchestrator' or env.get('GITHUB_REF') != 'refs/heads/main' or
        not re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', '')) or
        not re.fullmatch(r'[1-9][0-9]*', env.get('GITHUB_RUN_ID', '')) or
        not re.fullmatch(r'[1-9][0-9]*', env.get('GITHUB_RUN_ATTEMPT', '')) or
        env.get('GITHUB_WORKFLOW_REF') != ref or receipt.get('schema_version') != 'dev-feature-candidate/v2' or
        receipt.get('result') != 'verified' or receipt.get('stage') != 'sit' or
        receipt.get('candidate_sha256') != fingerprint or lane != {'feature_id': feature_id, 'feature_tag': tag, 'candidate_sha256': fingerprint} or
        producer.get('repository') != repo or producer.get('workflow_ref') != ref or
        producer.get('workflow_sha') != env.get('GITHUB_SHA') or producer.get('run_id') != env.get('GITHUB_RUN_ID') or
        producer.get('run_attempt') != env.get('GITHUB_RUN_ATTEMPT')):
        raise base.OperationError('candidate receipt is not bound to protected same-run tag')


class FeatureCloudflare(base.Cloudflare):
    def __init__(self, token: str, account_id: str, feature_id: str, feature_tag: str | None = None):
        super().__init__(token, account_id)
        self.feature_id = feature_id
        self.feature_tag = feature_tag

    def ownership_tags(self):
        tags = [f"feature-id:{self.feature_id}", "owner:iac-modules"]
        if self.feature_tag:
            tags.append(f"feature-tag:{self.feature_tag}")
        return sorted(tags)

    def records(self, zone_id: str, name: str) -> list[dict]:
        records = super().records(zone_id, name)
        if any(not set(self.ownership_tags()) <= set(r.get("tags") or []) for r in records):
            raise base.OperationError("DNS name is occupied by a record not owned by this Feature ID")
        return records

    def create_payload(self, payload: dict) -> dict:
        return dict(payload, comment=f"Codex SIT lane {self.feature_id}", tags=self.ownership_tags())

    def delete(self, zone_id: str, record_id: str) -> None:
        raise base.OperationError("DNS deletion requires an authenticated lane cleanup receipt; reconcile never deletes")


def main() -> int:
    try:
        feature_id = os.environ.get("FEATURE_ID", "").strip()
        service = os.environ.get("FEATURE_DNS_SERVICE", "").strip()
        zone = base.domain(base.required(os.environ, "DNS_ZONE"))
        if os.environ.get("DNS_ENVIRONMENT") != "sit":
            raise base.OperationError("feature DNS is SIT-only")
        name, tag = requested_domain(os.environ, feature_id, service, zone)
        fingerprint = None
        if tag is not None:
            fingerprint = base.required(os.environ, 'FEATURE_CANDIDATE_SHA256')
            if not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
                raise base.OperationError('authenticated candidate fingerprint required')
            verify_candidate_receipt(base.required(os.environ, 'FEATURE_CANDIDATE_RECEIPT'), feature_id, tag, fingerprint, os.environ)
        cmdb_raw = Path(base.required(os.environ, "CMDB_FILE")).read_bytes()
        if tag is not None:
            cmdb_sha = base.required(os.environ, 'CMDB_SHA256')
            if not re.fullmatch(r'[0-9a-f]{64}', cmdb_sha) or hashlib.sha256(cmdb_raw).hexdigest() != cmdb_sha:
                raise base.OperationError('authenticated CMDB digest mismatch')
        cmdb = json.loads(cmdb_raw)
        node = base.required(os.environ, "DEV_INGRESS_NODE")
        target = dev_ingress_ip(cmdb, node)
        observation = None
        if tag is not None:
            observation = verify_current_target(cmdb, target, base.required(os.environ, 'LINODE_TOKEN'))
            observation['cmdb_sha256'] = hashlib.sha256(cmdb_raw).hexdigest()
        env = dict(os.environ, DNS_ENVIRONMENT="sit", DNS_ZONE=zone, DNS_RECORD_NAME=name, DNS_TARGET_IP=target)
        config = base.Config.from_env(env, allowed_environments=("sit",))
        client = FeatureCloudflare(base.required(env, "CLOUDFLARE_DNS_API_TOKEN"), base.required(env, "CLOUDFLARE_ACCOUNT_ID"), feature_id, tag)
        result = base.execute(config, client)
        output = {"result": "verified", "feature_id": feature_id, "feature_tag": tag, "service": service, "hostname": name, **result}
        if observation is not None:
            output['provider_observation'] = observation
            output['candidate_sha256'] = fingerprint
        print(json.dumps(output, sort_keys=True))
        return 0
    except (base.OperationError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
