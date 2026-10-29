#!/usr/bin/env python3
"""Authenticate DNS inputs before requesting any provider credential."""
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('feature_dns_owner', HERE / 'cloudflare-sit-feature-dns.py')
owner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = owner
spec.loader.exec_module(owner)

def validate(env):
    owner.verify_candidate_receipt(env['FEATURE_CANDIDATE_RECEIPT'], env['FEATURE_ID'], env['FEATURE_TAG'], env['FEATURE_CANDIDATE_SHA256'], env)
    owner.verify_domain_contract(env['FEATURE_DOMAIN_CONTRACT'])
    host = owner.tagged_lane_domain(env['FEATURE_ID'], env['FEATURE_TAG'], env['FEATURE_DNS_SERVICE'], 'onwalk.net')
    if host != env['FEATURE_HOSTNAME']:
        raise ValueError('candidate hostname mismatch')
    raw = Path(env['CMDB_FILE']).read_bytes()
    cmdb_hash = hashlib.sha256(raw).hexdigest()
    if not re.fullmatch('[0-9a-f]{64}', env['CMDB_SHA256']) or cmdb_hash != env['CMDB_SHA256']:
        raise ValueError('CMDB digest mismatch')
    target = owner.dev_ingress_ip(json.loads(raw), 'dev-k3s-v5')
    observation = json.loads(Path(env['TARGET_OBSERVATION']).read_text())
    when = datetime.datetime.fromisoformat(observation['observed_at'])
    now = datetime.datetime.now(datetime.timezone.utc)
    if (observation.get('schema') != 'dev-sit-provider-observation/v1' or observation.get('result') != 'MATCH' or
        observation.get('node') != 'dev-k3s-v5' or observation.get('ip') != target or
        observation.get('instance_id') != str(json.loads(raw)['dev-k3s-v5']['instance_id']) or
        observation.get('cmdb_sha256') != cmdb_hash or observation.get('candidate_sha256') != env['FEATURE_CANDIDATE_RECEIPT_SHA256'] or
        when.tzinfo is None or not datetime.timedelta(0) <= now - when <= datetime.timedelta(minutes=20)):
        raise ValueError('fresh same-run provider observation mismatch')

if __name__ == '__main__':
    try:
        validate(os.environ)
    except Exception:
        print('::error::Feature DNS preflight rejected its evidence', file=sys.stderr)
        sys.exit(1)
