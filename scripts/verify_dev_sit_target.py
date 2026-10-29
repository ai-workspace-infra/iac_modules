#!/usr/bin/env python3
"""Read-only comparison of a fixed Dev CMDB target to the provider API.

The caller must authenticate the CMDB producer and this script's workflow run;
this document alone is not an authenticated receipt or deployment approval.
"""
import argparse
import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys

from akamai_state_preflight import _linode_get_one, PreflightError


def validate_cmdb(cmdb, instance_id):
    if not re.fullmatch(r'[1-9][0-9]{0,11}', instance_id) or not isinstance(cmdb, dict) or set(cmdb) != {'dev-k3s-v5'}:
        raise ValueError('invalid Dev target')
    host = cmdb['dev-k3s-v5']
    if not isinstance(host, dict) or str(host.get('instance_id')) != instance_id or host.get('name') != 'dev-k3s-v5' or host.get('label') != 'dev-k3s-v5':
        raise ValueError('CMDB identity mismatch')
    ip = str(ipaddress.IPv4Address(host.get('ip', '')))
    if not ipaddress.IPv4Address(ip).is_global:
        raise ValueError('Dev public IPv4 required')
    return ip


def validate(cmdb, body, instance_id):
    ip = validate_cmdb(cmdb, instance_id)
    if (not isinstance(body, dict) or type(body.get('id')) is not int or str(body['id']) != instance_id or
        body.get('label') != 'dev-k3s-v5' or body.get('region') != 'jp-tyo-3' or
        body.get('status') != 'running' or not isinstance(body.get('ipv4'), list) or ip not in body['ipv4']):
        raise ValueError('provider target differs from CMDB')
    return ip


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cmdb', required=True, type=Path)
    parser.add_argument('--instance-id', required=True)
    parser.add_argument('--cmdb-sha256', required=True)
    parser.add_argument('--candidate-sha256', required=True)
    args = parser.parse_args()
    try:
        raw = args.cmdb.read_bytes()
        if len(raw) > 1_000_000:
            raise ValueError('CMDB too large')
        if (not re.fullmatch(r'[0-9a-f]{64}', args.cmdb_sha256) or
                not re.fullmatch(r'[0-9a-f]{64}', args.candidate_sha256) or
                hashlib.sha256(raw).hexdigest() != args.cmdb_sha256):
            raise ValueError('candidate or authenticated CMDB digest mismatch')
        cmdb = json.loads(raw)
        validate_cmdb(cmdb, args.instance_id)
        status, body = _linode_get_one('linode/instances/' + args.instance_id, os.environ.get('LINODE_TOKEN', ''))
        if status != 200:
            raise ValueError('provider lookup failed')
        ip = validate(cmdb, body, args.instance_id)
        print(json.dumps({'schema':'dev-sit-provider-observation/v1','result':'MATCH',
                          'instance_id':args.instance_id,'node':'dev-k3s-v5','ip':ip,
                          'cmdb_sha256':args.cmdb_sha256, 'candidate_sha256':args.candidate_sha256,
                          'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, PreflightError):
        print('::error::Dev SIT provider target verification failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
