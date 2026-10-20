#!/usr/bin/env python3
"""Switch reviewed existing A/CNAME records with durable, resumable checkpoints."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('record_switch_owner', Path(__file__).with_name('cloudflare-gateway-dns-upsert.py'))
owner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = owner
spec.loader.exec_module(owner)


def require(ok, message):
    if not ok:
        raise owner.OperationError(message)


def normalize(plan):
    require(plan.get('environment') in ('uat', 'prod'), 'explicit environment required')
    require(isinstance(plan.get('records'), list) and 0 < len(plan['records']) <= 20, 'bounded record list required')
    names = set()
    for row in plan['records']:
        require(set(row) == {'zone', 'name', 'type', 'expected_content', 'content'}, 'unexpected record fields')
        require(row['type'] in ('A', 'CNAME'), 'only existing A/CNAME records may switch')
        zone, name = owner.domain(row['zone']), owner.domain(row['name'])
        require(zone == row['zone'] and name == row['name'], 'noncanonical record name')
        require(name == zone or name.endswith('.' + zone), 'record outside its zone')
        require(name not in names, 'duplicate record name')
        names.add(name)
        validate = owner.public_ipv4 if row['type'] == 'A' else owner.domain
        require(validate(row['content']) == row['content'] and validate(row['expected_content']) == row['expected_content'], 'noncanonical record content')
        require(row['content'] != row['expected_content'], 'source and target are identical')
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def selected(client, zone_id, row):
    records = client.records(zone_id, row['name'])
    matches = [r for r in records if r.get('type') == row['type']]
    require(len(matches) == 1, 'expected exactly one managed address/alias record')
    require(not any(r.get('type') in ('A', 'AAAA', 'CNAME') and r.get('id') != matches[0].get('id') for r in records), 'conflicting address or alias record')
    return matches[0]


def execute(plan, client, checkpoint, apply=False):
    digest = normalize(plan)
    require(checkpoint.is_absolute() and not checkpoint.is_symlink(), 'absolute private checkpoint required')
    checkpoint.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    require(checkpoint.parent.stat().st_mode & 0o077 == 0, 'checkpoint parent must be private')
    lock_path = checkpoint.with_suffix(checkpoint.suffix + '.lock')
    with lock_path.open('a') as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if checkpoint.exists():
            state = json.loads(checkpoint.read_text())
            require(state.get('plan_sha256') == digest, 'checkpoint belongs to another plan')
        else:
            items = []
            for row in plan['records']:
                zone_id = client.zone_id(row['zone'])
                record = selected(client, zone_id, row)
                require(record.get('content') == row['expected_content'], 'source DNS differs from reviewed plan')
                original = owner.record_payload(record)
                items.append({'row': row, 'zone_id': zone_id, 'record_id': record['id'],
                              'original': original, 'desired': dict(original, content=row['content']), 'done': False})
            state = {'plan_sha256': digest, 'items': items, 'status': 'prepared'}
        # Validate the entire saved set before making another write. MX/TXT and
        # unrelated names are never mutation targets.
        for item in state['items']:
            current = selected(client, item['zone_id'], item['row'])
            require(current.get('id') == item['record_id'], 'provider record identity changed')
            require(owner.record_payload(current) in (item['original'], item['desired']), 'DNS changed concurrently')
        if not apply:
            return {'status': 'preview', 'plan_sha256': digest, 'record_count': len(state['items'])}
        owner.save_checkpoint(checkpoint, state)
        for item in state['items']:
            current = selected(client, item['zone_id'], item['row'])
            actual = owner.record_payload(current)
            require(current.get('id') == item['record_id'] and actual in (item['original'], item['desired']), 'record changed before update')
            if actual != item['desired']:
                client.update(item['zone_id'], item['record_id'], item['desired'])
            require(owner.record_payload(selected(client, item['zone_id'], item['row'])) == item['desired'], 'provider verification failed; retain checkpoint')
            item['done'] = True
            owner.save_checkpoint(checkpoint, state)
        state['status'] = 'provider-verified'
        owner.save_checkpoint(checkpoint, state)
        return {'status': state['status'], 'plan_sha256': digest, 'record_count': len(state['items'])}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        client = owner.Cloudflare(owner.required(os.environ, 'CLOUDFLARE_DNS_API_TOKEN'), owner.required(os.environ, 'CLOUDFLARE_ACCOUNT_ID'))
        print(json.dumps(execute(json.load(sys.stdin), client, args.checkpoint, args.apply)))
    except (owner.OperationError, ValueError, KeyError, BlockingIOError):
        print('DNS switch stopped; inspect the protected plan/checkpoint', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
