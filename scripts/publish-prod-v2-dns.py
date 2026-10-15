#!/usr/bin/env python3
"""Create new V2 records only; refuse to alter pre-existing DNS records."""
import argparse
import json
import pathlib
import urllib.parse
import urllib.request
import yaml

p = argparse.ArgumentParser()
p.add_argument('--manifest', required=True)
p.add_argument('--cmdb', required=True)
p.add_argument('--apply', action='store_true')
a = p.parse_args()
spec = yaml.safe_load(pathlib.Path(a.manifest).read_text())['spec']
hosts = yaml.safe_load(pathlib.Path(a.cmdb).read_text())['instances']
by_role = {x['role']: x['ip'] for x in hosts}
assert spec['dns_cutover'] is False
token = pathlib.Path.home().joinpath('.vault-token').read_text().strip()
request = urllib.request.Request('https://vault.svc.plus/v1/kv/data/CICD', headers={'X-Vault-Token': token})
with urllib.request.urlopen(request, timeout=15) as response:
    data = json.load(response)['data']['data']
cf_token = data['CLOUDFLARE_DNS_API_TOKEN']


def api(path, body=None):
    request = urllib.request.Request('https://api.cloudflare.com/client/v4/' + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + cf_token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)
    if not result['success']:
        raise SystemExit('Cloudflare operation failed')
    return result['result']


zones = api('zones?name=svc.plus')
assert len(zones) == 1
zone = zones[0]['id']
for role, name in spec['domains'].items():
    assert name.endswith('-prod-v2.svc.plus')
    ip = by_role[role if role in ('free', 'plus', 'team') else 'control']
    records = api(f'zones/{zone}/dns_records?name=' + urllib.parse.quote(name))
    if records:
        assert len(records) == 1 and records[0]['type'] == 'A' and records[0]['content'] == ip, 'Refusing to change existing DNS: ' + name
        print(name, 'already matches V2')
    elif a.apply:
        api(f'zones/{zone}/dns_records', {'type': 'A', 'name': name, 'content': ip, 'ttl': 300, 'proxied': False})
        print('Created', name, ip)
    else:
        print('Would create', name, ip)
