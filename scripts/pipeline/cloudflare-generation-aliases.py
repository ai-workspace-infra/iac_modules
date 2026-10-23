#!/usr/bin/env python3
"""Create only a generation's four origin aliases using the existing DNS owner."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

import yaml

spec = importlib.util.spec_from_file_location('generation_dns_owner', Path(__file__).with_name('cloudflare-gateway-dns-upsert.py'))
owner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = owner
spec.loader.exec_module(owner)


def plan(generation, address):
    if not re.fullmatch(r'prod-v[1-9][0-9]*', generation):
        raise owner.OperationError('explicit prod-vN generation required')
    address = owner.public_ipv4(address)
    return [{'name': service + '-selfhost-' + generation + '.svc.plus', 'address': address}
            for service in ('console', 'accounts', 'billing', 'postgresql')]


def render_sources(resources, cmdb_path):
    """Bind the exact generation aliases to a GitOps declaration and IaC CMDB."""
    resources = Path(resources)
    cmdb_path = Path(cmdb_path)
    try:
        resource_bytes = resources.read_bytes()
        cmdb_bytes = cmdb_path.read_bytes()
        declaration = yaml.safe_load(resource_bytes) or {}
        cmdb = json.loads(cmdb_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as error:
        raise owner.OperationError("unable to read GitOps resources or IaC CMDB") from error

    global_config = declaration.get('global') or {}
    if (global_config.get('provider') != 'akamai-cloud'
            or global_config.get('environment') != 'prod'
            or global_config.get('project') != 'svc.plus'):
        raise owner.OperationError('DNS source must be svc.plus Akamai PROD GitOps')
    hosts = declaration.get('hosts')
    if not isinstance(hosts, list) or len(hosts) != 1 or not isinstance(hosts[0], dict):
        raise owner.OperationError('DNS source must declare exactly one host')
    host = hosts[0]
    host_vars = host.get('host_vars') or {}
    generation = host_vars.get('target_generation')
    if not isinstance(generation, str) or not re.fullmatch(r'prod-v[1-9][0-9]*', generation):
        raise owner.OperationError('explicit prod-vN target_generation required')
    expected_domains = [
        service + '-selfhost-' + generation + '.svc.plus'
        for service in ('console', 'accounts', 'billing', 'postgresql')
    ]
    domains = host_vars.get('service_domains')
    if domains != expected_domains:
        raise owner.OperationError('GitOps service_domains do not match the four generation aliases')

    if not isinstance(cmdb, dict):
        raise owner.OperationError('IaC CMDB must be a host mapping')
    matches = [
        entry for entry in cmdb.values()
        if isinstance(entry, dict) and entry.get('name') == host.get('name')
    ]
    if len(matches) != 1:
        raise owner.OperationError('IaC CMDB must contain exactly one matching host')
    entry = matches[0]
    cmdb_host_vars = entry.get('host_vars') or {}
    if cmdb_host_vars.get('service_domains') != domains:
        raise owner.OperationError('GitOps and IaC CMDB service_domains differ')
    if cmdb_host_vars.get('target_generation') != generation:
        raise owner.OperationError('GitOps and IaC CMDB target generations differ')
    if entry.get('fqdn') != domains[0] or not entry.get('instance_id'):
        raise owner.OperationError('IaC CMDB host identity is incomplete or mismatched')

    address = entry.get('ip')
    if not isinstance(address, str):
        raise owner.OperationError('IaC CMDB public IP is missing or invalid')
    address = owner.public_ipv4(address)
    return {
        'generation': generation,
        'address': address,
        'records': plan(generation, address),
        'source_sha256': {
            'gitops': hashlib.sha256(resource_bytes).hexdigest(),
            'cmdb': hashlib.sha256(cmdb_bytes).hexdigest(),
        },
    }


def run(client, generation, address, checkpoint, apply=False):
    records = plan(generation, address)
    zone_id = client.zone_id('svc.plus')
    preview = []
    # Validate all exact names before the first write. Never clean up duplicate
    # or non-A records implicitly; a single existing A may be updated in place.
    for row in records:
        before = client.records(zone_id, row['name'])
        if len(before) > 1 or any(v.get('type') != 'A' for v in before):
            raise owner.OperationError('generation alias conflict; no DNS changes started')
        current = before[0] if before else None
        desired = None if current is None else dict(
            owner.record_payload(current), content=row['address'], ttl=60, proxied=False
        )
        action = 'create' if current is None else (
            'noop' if owner.record_payload(current) == desired else 'update'
        )
        preview.append({
            **row,
            'action': action,
            'current_address': None if current is None else current.get('content'),
        })
    if not apply:
        return {'status': 'preview', 'records': preview, 'public_aliases_modified': False}
    if not checkpoint.is_absolute() or checkpoint.is_symlink():
        raise owner.OperationError('absolute private checkpoint directory required')
    checkpoint.mkdir(mode=0o700, parents=True, exist_ok=True)
    if checkpoint.stat().st_mode & 0o077:
        raise owner.OperationError('checkpoint directory must have mode 0700')
    results = []
    for row in records:
        config = owner.Config('prod', client.account_id, 'svc.plus', row['name'], row['address'],
                              checkpoint / (row['name'] + '.json'), True)
        results.append(dict(name=row['name'], **owner.execute(config, client)))
    return {'status': 'verified', 'records': results, 'public_aliases_modified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--resources', type=Path, help='fixed GitOps Akamai PROD resource YAML')
    source.add_argument('--generation', help='legacy direct-input mode; prefer --resources and --cmdb')
    parser.add_argument('--cmdb', type=Path, help='IaC-generated CMDB JSON for --resources')
    parser.add_argument('--address', help='target IPv4 for legacy --generation mode')
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        if args.resources:
            if not args.cmdb or args.address:
                parser.error('--resources requires --cmdb and cannot be combined with --address')
            target = render_sources(args.resources, args.cmdb)
        else:
            if args.cmdb or not args.address:
                parser.error('--generation requires --address and cannot be combined with --cmdb')
            target = {
                'generation': args.generation,
                'address': owner.public_ipv4(args.address),
                'records': plan(args.generation, args.address),
                'source_sha256': None,
            }
        client = owner.Cloudflare(owner.required(os.environ, 'CLOUDFLARE_DNS_API_TOKEN'),
                                  owner.required(os.environ, 'CLOUDFLARE_ACCOUNT_ID'))
        result = run(client, target['generation'], target['address'], args.checkpoint, args.apply)
        desired = target['records']
        if [row['name'] for row in result['records']] != [row['name'] for row in desired]:
            raise owner.OperationError('provider result scope differs from rendered GitOps scope')
        if any(row['address'] != expected['address']
               for row, expected in zip(result['records'], desired)):
            raise owner.OperationError('provider result target differs from rendered CMDB IP')
        result['source_sha256'] = target['source_sha256']
        print(json.dumps(result))
        return 0
    except owner.OperationError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
