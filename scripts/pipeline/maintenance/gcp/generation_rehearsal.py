#!/usr/bin/env python3
"""Local operator: add one rehearsal generation in the retained Web SaaS state.

Uses the existing renderer/backend owner; refuses any change to old VMs/disks.
Credentials stay in process memory and private Terraform files. No DNS writes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import yaml

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts/pipeline'))
from unified import runtime
from unified.contracts import digest


def output(command):
    p = subprocess.run(command, capture_output=True)
    if p.returncode:
        raise RuntimeError('operator credential or source check failed')
    return p.stdout.decode().strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--gitops', required=True)
    parser.add_argument('--generation', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'prod-v[1-9][0-9]*', args.generation) or int(args.generation[6:]) < 4:
        raise RuntimeError('requires an explicit new generation')
    gitops = Path(args.gitops).resolve()
    for repo in (ROOT, gitops):
        if output(['git', '-C', str(repo), 'status', '--porcelain']):
            raise RuntimeError('pin clean committed checkouts before planning')
    target = yaml.safe_load((gitops/'iac/targets/prod-gcp-web-saas.yaml').read_text())['targets'][0]
    spec = target['stages']['resources']
    spec['manifest_sha256'] = digest(gitops / spec['manifest'])
    document = yaml.safe_load((gitops / spec['manifest']).read_text())['spec']
    name = 'web-saas-' + args.generation
    declared = [vm for vm in document['resources']['service_vms'] if vm['name'] == name]
    if len(declared) != 1 or document['project_id'] != 'open-platform-prod':
        raise RuntimeError('generation or project not declared')
    os.umask(0o077)
    private = Path(tempfile.mkdtemp(prefix='gcp-generation-rehearsal-'))
    # Reuse the authenticated local Vault session, without exporting its token.
    state = json.loads(output(['vault', 'kv', 'get', '-format=json', 'kv/CICD/prod/iac_state']))['data']['data']
    for key in ['TF_STATE_BUCKET','TF_STATE_REGION','TF_STATE_ENDPOINT','TF_STATE_ACCESS_KEY','TF_STATE_SECRET_KEY']:
        os.environ[key] = state[key]
    os.environ['GOOGLE_OAUTH_ACCESS_TOKEN'] = output(['gcloud','auth','print-access-token'])
    os.environ['AWS_ACCESS_KEY_ID'] = state['TF_STATE_ACCESS_KEY']
    os.environ['AWS_SECRET_ACCESS_KEY'] = state['TF_STATE_SECRET_KEY']
    os.environ['AWS_SESSION_TOKEN'] = ''
    os.environ['TF_VAR_deploy_service_account'] = 'github-actions-prod@open-platform-prod.iam.gserviceaccount.com'
    oidc = yaml.safe_load((gitops/'resources/xworktech.com/prod/gcp/github-actions-oidc.yaml').read_text())
    os.environ['TF_VAR_workload_identity_provider'] = oidc['spec']['audience'].removeprefix('https://iam.googleapis.com/')
    profile = json.loads(output(['gcloud','compute','os-login','describe-profile','--project=open-platform-prod','--format=json']))
    names = {p['username'] for p in profile.get('posixAccounts',[]) if p.get('operatingSystemType') == 'LINUX'}
    if len(names) != 1:
        raise RuntimeError('authenticated operator has no unique Linux OS Login profile')
    os.environ['GCP_OSLOGIN_USERNAME'] = names.pop()
    root, _ = runtime.render({},target,'resources',ROOT,gitops,private)
    runtime.initialize(root,private,spec['state'])
    before = runtime.terraform(root,private,'state','pull').stdout
    current_state = json.loads(before)
    if not any(r.get('module') == 'module.spot_web_saas_prod_v3' for r in current_state.get('resources', [])):
        raise RuntimeError('retained V3 owner state is missing')
    (private/'before.tfstate').write_bytes(before)
    os.chmod(private/'before.tfstate',0o600)
    plan = private/'reviewed.tfplan'
    runtime.terraform(root,private,'plan','-input=false','-lock-timeout=5m',f'-out={plan}','-no-color')
    doc = json.loads(runtime.terraform(root,private,'show','-json',str(plan)).stdout)
    changes = []
    marker = name.replace('-','_')
    shared = {'google_org_policy_policy.vm_external_ip_access','google_compute_firewall.spot_ssh_iap'}
    for item in doc.get('resource_changes',[]):
        change = item['change']; actions = change['actions']; address = item['address']
        if item['mode'] == 'data' or actions == ['no-op']: continue
        if address in shared and actions == ['update']:
            before_value, after_value = change['before'],change['after']
            if address.endswith('spot_ssh_iap'):
                if not set(before_value['target_tags']).issubset(after_value['target_tags']):
                    raise RuntimeError('existing IAP access would be removed')
                if before_value['source_ranges'] != after_value['source_ranges']:
                    raise RuntimeError('IAP source range changed')
            else:
                old = before_value['spec'][0]['rules'][0]['values'][0]['allowed_values']
                new = after_value['spec'][0]['rules'][0]['values'][0]['allowed_values']
                expected = f"projects/open-platform-prod/zones/{declared[0]['zone']}/instances/{name}"
                if set(new) != set(old) | {expected}:
                    raise RuntimeError('external-IP policy changed beyond new generation')
        elif marker in address and actions == ['create']:
            pass
        else:
            raise RuntimeError('plan changes existing or unrelated resource: '+address)
        changes.append({'address':address,'actions':actions})
    evidence = {'generation':args.generation,'iac_sha':output(['git','-C',str(ROOT),'rev-parse','HEAD']),
                'gitops_sha':output(['git','-C',str(gitops),'rev-parse','HEAD']),
                'plan_sha256':hashlib.sha256(plan.read_bytes()).hexdigest(),'changes':changes,'result':'planned'}
    (private/'receipt.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps({'evidence':str(private/'receipt.json'),**evidence}),flush=True)
    if args.apply:
        runtime.terraform(root,private,'apply','-input=false','-lock-timeout=5m','-no-color',str(plan))
        runtime.terraform(root,private,'plan','-input=false','-lock-timeout=5m','-detailed-exitcode','-no-color')
        runtime.run([sys.executable,str(ROOT/'terraform-hcl-standard/gcp-cloud/scripts/generate.py'),'inventory','--resources',str(gitops/spec['manifest']),'--workdir',str(root)],private)
        evidence['result']='applied_verified'
        evidence['cmdb']=str(root/'cmdb.json')
        (private/'receipt.json').write_text(json.dumps(evidence,indent=2)+'\n')
        print(json.dumps(evidence),flush=True)


if __name__ == '__main__':
    try: main()
    except Exception as error:
        # Provider diagnostics may contain credentials; only private logs retain them.
        print('generation rehearsal stopped: '+(str(error) if isinstance(error,RuntimeError) else type(error).__name__),file=sys.stderr)
        sys.exit(1)
