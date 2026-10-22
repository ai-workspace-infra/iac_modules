#!/usr/bin/env python3
"""Create only a generation's four origin aliases using the existing DNS owner."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

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


def run(client, generation, address, checkpoint, apply=False):
    records = plan(generation, address)
    zone_id = client.zone_id('svc.plus')
    # Validate every exact name before the first write. Existing other targets
    # or record types must be investigated instead of overwritten.
    for row in records:
        before = client.records(zone_id, row['name'])
        if len(before) > 1 or any(v.get('type') != 'A' or v.get('content') != row['address'] for v in before):
            raise owner.OperationError('generation alias conflict; no DNS changes started')
    if not apply:
        return {'status': 'preview', 'records': records, 'public_aliases_modified': False}
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
    parser.add_argument('--generation', required=True)
    parser.add_argument('--address', required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        client = owner.Cloudflare(owner.required(os.environ, 'CLOUDFLARE_DNS_API_TOKEN'),
                                  owner.required(os.environ, 'CLOUDFLARE_ACCOUNT_ID'))
        print(json.dumps(run(client, args.generation, args.address, args.checkpoint, args.apply)))
        return 0
    except owner.OperationError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
