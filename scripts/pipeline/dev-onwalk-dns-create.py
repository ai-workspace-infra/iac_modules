#!/usr/bin/env python3
"""Create only six Dev web-saas onwalk A records from verified live IaC identity."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys

from unified.auth import request_json

spec=importlib.util.spec_from_file_location('dev_dns_shared_cloudflare',Path(__file__).with_name('cloudflare-gateway-dns-upsert.py'))
shared=importlib.util.module_from_spec(spec);sys.modules[spec.name]=shared;spec.loader.exec_module(shared)
Error=shared.OperationError
ZONE='onwalk.net'
NAMES=tuple(sorted(prefix+'.'+ZONE for prefix in (
    'xconnect-referral-sit','accounts-xconnect-referral-sit','billing-xconnect-referral-sit',
    'web-saas-uat','accounts-web-saas-uat','billing-web-saas-uat')))
TARGET='dev-akamai-dev-k3s-v5';HOST='dev-k3s-v5'


def require(condition, reason):
    if not condition:raise Error(reason)


def validate(plan, raw_cmdb):
    require(isinstance(plan,dict) and set(plan)=={'schema','environment','feature_id','zone','hostnames','gitops_sha','cmdb_sha256','operation_id','expected_target'},'invalid explicit Dev plan fields')
    require(plan['schema']=='dev-onwalk-dns/v1' and plan['environment']=='dev' and plan['feature_id']=='xconnect-referral'
            and plan['zone']==ZONE,'Dev onwalk scope required')
    require(isinstance(plan['hostnames'],list) and len(plan['hostnames'])==6 and set(plan['hostnames'])==set(NAMES),'exact six approved hostnames required')
    require(re.fullmatch(r'[a-f0-9]{40}',plan['gitops_sha'] or '') and re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',plan['operation_id'] or ''),'reviewed GitOps SHA and operation ID required')
    require(hashlib.sha256(raw_cmdb).hexdigest()==plan['cmdb_sha256'],'CMDB artifact checksum differs')
    expected=plan['expected_target']
    require(isinstance(expected,dict) and set(expected)=={'target_id','instance_id','name','label','region','account'},'exact expected cloud identity required')
    require(expected['target_id']==TARGET and expected['name']==HOST and expected['label']==HOST
            and re.fullmatch(r'[1-9][0-9]*',str(expected['instance_id'])) and re.fullmatch(r'[a-z0-9-]+',expected['region'] or '')
            and re.fullmatch(r'[A-Za-z0-9_.-]+',expected['account'] or ''),'one explicit Dev instance required')
    cmdb=json.loads(raw_cmdb)
    require(isinstance(cmdb,dict) and set(cmdb)=={TARGET} and isinstance(cmdb[TARGET],dict) and set(cmdb[TARGET])=={HOST},'single Dev target CMDB required')
    host=cmdb[TARGET][HOST]
    require(host.get('name')==HOST and host.get('label')==HOST and str(host.get('instance_id'))==str(expected['instance_id'])
            and host.get('region')==expected['region'] and host.get('host_vars',{}).get('cloud_provider')=='akamai-cloud'
            and host.get('host_vars',{}).get('k3s_platform_cluster_name')==HOST
            and 'dev' in host.get('groups',[]) and not {'prod','uat','production'} & set(host.get('groups',[])), 'CMDB does not describe the exact Dev resource')
    address=shared.public_ipv4(host.get('ip',''));require(ipaddress.ip_address(address).is_global,'globally routed IPv4 required')
    return address


class LinodeReadOnly:
    def __init__(self, token):self.headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
    def get(self,path,label=None):
        headers=dict(self.headers)
        if label is not None:headers['X-Filter']=json.dumps({'label':label})
        # Only fixed read endpoints; no provider mutation, console or SSH.
        require(path in ('/profile','/linode/instances?page_size=100') or re.fullmatch(r'/linode/instances/[1-9][0-9]*',path),'unapproved provider read')
        try:
            return request_json('https://api.linode.com/v4'+path,headers,method='GET')
        except Exception:
            raise Error('Linode read failed; response details withheld') from None


def verify_live(linode, expected, address):
    require(linode.get('/profile').get('username')==expected['account'],'Linode account mismatch')
    current=linode.get('/linode/instances/'+str(expected['instance_id']))
    require(str(current.get('id'))==str(expected['instance_id']) and current.get('label')==HOST
            and current.get('region')==expected['region'] and current.get('status')=='running'
            and address in current.get('ipv4',[]),'current cloud ID/label/region/address differs')
    listing=linode.get('/linode/instances?page_size=100',label=HOST)
    rows=listing.get('data',[])
    require(listing.get('pages')==1 and listing.get('results')==1 and len(rows)==1
            and str(rows[0].get('id'))==str(expected['instance_id']) and rows[0].get('label')==HOST,'Dev label must uniquely identify the selected instance')


def owned_record(records, name, state, desired):
    known=state['records'].get(name)
    if not records:
        require(known is None,'previously created record disappeared; manual review required')
        return False
    require(len(records)==1 and known is not None,'pre-existing or concurrent DNS record; no adoption or overwrite')
    row=records[0]
    require(row.get('id')==known and all(row.get(key)==value for key,value in desired.items()),'record ID/owner/target/attributes changed')
    return True


def execute(plan, raw_cmdb, checkpoint, cf, linode, account, apply=False):
    address=validate(plan,raw_cmdb)
    require(re.fullmatch(r'[a-f0-9]{32}',account or ''),'explicit Cloudflare account ID required')
    checkpoint=Path(checkpoint)
    require(checkpoint.is_absolute() and not checkpoint.is_symlink(),'absolute nonsymlink checkpoint required')
    checkpoint.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    require(stat.S_IMODE(checkpoint.parent.stat().st_mode)&0o077==0,'private checkpoint parent required')
    lock_path=checkpoint.with_name(checkpoint.name+'.lock');require(not lock_path.is_symlink(),'unsafe checkpoint lock')
    with lock_path.open('a+') as lock:
        os.chmod(lock_path,0o600);fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        verify_live(linode,plan['expected_target'],address)
        zone=cf.zone_id(ZONE)
        details=cf.request('GET','/zones/'+zone)
        require(details.get('id')==zone and details.get('name')==ZONE and details.get('status')=='active'
                and details.get('account',{}).get('id')==account,'active onwalk zone/account mismatch')
        fingerprint=hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        marker='dev-onwalk:'+fingerprint
        binding={'version':1,'environment':'dev','zone':ZONE,'zone_id':zone,'account_id':account,
                 'plan_sha256':fingerprint,'cmdb_sha256':plan['cmdb_sha256'],'gitops_sha':plan['gitops_sha'],
                 'instance_id':str(plan['expected_target']['instance_id']),'address':address,'owner':marker}
        if checkpoint.exists():
            state=json.loads(checkpoint.read_text())
            require(isinstance(state,dict) and all(state.get(k)==v for k,v in binding.items())
                    and isinstance(state.get('records'),dict) and set(state['records'])<=set(NAMES),'checkpoint scope mismatch')
        else:state={**binding,'records':{},'result':'PREFLIGHT'}
        payloads={name:{'type':'A','name':name,'content':address,'ttl':60,'proxied':False,'comment':marker} for name in NAMES}
        # Read all six names and reject *any* unowned A/AAAA/CNAME/etc before first create.
        for name in NAMES:owned_record(cf.records(zone,name),name,state,payloads[name])
        if not apply:return {**binding,'result':'PLANNED','created_records':dict(state['records']),'hostnames':list(NAMES),'dns_resolution':'NOT_RUN','tls':'NOT_RUN'}
        shared.save_checkpoint(checkpoint,state)
        try:
            for name in NAMES:
                # Re-read immediately before creation; never overwrite a concurrent record.
                if owned_record(cf.records(zone,name),name,state,payloads[name]):continue
                # Recheck dynamic identity before each mutation, not only at initial preflight.
                verify_live(linode,plan['expected_target'],address)
                created=cf.create(zone,payloads[name])
                require(isinstance(created.get('id'),str) and bool(created['id']),'create returned no record identity')
                state['records'][name]=created['id'];state['result']='PARTIAL'
                shared.save_checkpoint(checkpoint,state)
                owned_record(cf.records(zone,name),name,state,payloads[name])
            state['result']='CREATED_API_VERIFIED';shared.save_checkpoint(checkpoint,state)
        except Exception:
            state['result']='BLOCKED_PARTIAL';shared.save_checkpoint(checkpoint,state)
            raise Error('Dev DNS operation incomplete; preserve checkpoint IDs for retry or review') from None
        return {**binding,'result':state['result'],'created_records':dict(state['records']),'hostnames':list(NAMES),'dns_resolution':'NOT_RUN','tls':'NOT_RUN'}


def read_bytes(path):
    value=Path(path);require(value.is_file() and not value.is_symlink() and value.stat().st_size<=1_000_000,'bounded input file required')
    return value.read_bytes()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--plan',required=True);parser.add_argument('--cmdb',required=True)
    parser.add_argument('--checkpoint',required=True);parser.add_argument('--apply',action='store_true');a=parser.parse_args()
    os.umask(0o077)
    try:
        result=execute(json.loads(read_bytes(a.plan)),read_bytes(a.cmdb),a.checkpoint,
                       shared.Cloudflare(shared.required(os.environ,'CF_API_TOKEN'),shared.required(os.environ,'CF_ACCOUNT')),
                       LinodeReadOnly(shared.required(os.environ,'LINODE_TOKEN')),shared.required(os.environ,'CF_ACCOUNT'),a.apply)
        print(json.dumps(result,sort_keys=True));return 0
    except Exception:
        # Never emit provider response bodies, headers, environment or exception values.
        print('Dev DNS BLOCKED: verify plan/CMDB/current identity/zone/conflicts; preserve checkpoint, no rollback performed.',file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
