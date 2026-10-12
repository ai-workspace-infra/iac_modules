#!/usr/bin/env python3
"""Offline non-secret render. No automatic import, cloud calls or secret expansion."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import yaml

ROOT=Path(__file__).resolve().parents[1]

class RenderRejected(ValueError): pass

def require(test, code):
    if not test: raise RenderRejected(code)

def load_declaration(path):
    data=yaml.safe_load(Path(path).read_text())
    require(type(data) is dict and set(data) == {'global','database'}, 'invalid_declaration')
    g,d=data['global'],data['database']
    require(type(g) is dict and set(g) <= {'management_mode','project_ref','organization_id','project_name','region','instance_size','pooler_mode','strict_no_secret_state','ack_sensitive_state','explicit_adoption'}, 'nonsecret_global_only')
    require(type(d) is dict and set(d) <= {'username','name','uri_env'}, 'nonsecret_database_only')
    mode=g.get('management_mode')
    require(mode in ('existing_external','adopt_existing','create_new'), 'explicit_management_mode_required')
    for flag in ('strict_no_secret_state','ack_sensitive_state','explicit_adoption'):
        require(type(g.get(flag)) is bool, 'explicit_safety_flags_required')
    require(g['explicit_adoption'] == (mode == 'adopt_existing'), 'explicit_adoption_required')
    for k,v in g.items():
        if k not in ('management_mode','strict_no_secret_state','ack_sensitive_state','explicit_adoption') and v is not None:
            require(type(v) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',v), 'invalid_nonsecret_value')
    for k,v in d.items():
        require(type(v) is str and re.fullmatch(r'[A-Za-z0-9_]{1,63}',v), 'invalid_database_metadata')
    require(all(d.get(k) for k in ('username','name')), 'database_metadata_required')
    if mode == 'create_new': require(not g.get('project_ref'), 'create_new_has_project_ref')
    else: require(bool(g.get('project_ref')), 'existing_project_ref_required')
    if mode != 'existing_external':
        require(all(g.get(k) for k in ('organization_id','project_name','region')), 'project_metadata_required')
        require(not g['strict_no_secret_state'] and g['ack_sensitive_state'], 'provider_secret_state_unsupported')
    return data

def render(args):
    data=load_declaration(args.resources); g,d=data['global'],data['database']; mode=g['management_mode']
    workdir=Path(args.workdir).resolve()
    # Fresh output only: never read state or overwrite an established workdir/import.
    require(not workdir.exists() or not any(workdir.iterdir()), 'fresh_workdir_required')
    workdir.mkdir(parents=True,exist_ok=True)
    if mode == 'existing_external':
        (workdir/'main.tf').write_text('variable "project_ref" { type = string }\noutput "project_ref" { value = var.project_ref }\n')
        tfvars={'project_ref':g['project_ref']}
    else:
        for filename in ('provider.tf','variables.tf','main.tf','outputs.tf'):
            shutil.copyfile(ROOT/'contract_templates'/filename,workdir/filename)
        tfvars={'management_mode':mode,'project_ref':g.get('project_ref'),
                'organization_id':g['organization_id'],'project_name':g['project_name'],
                'region':g['region'],'instance_size':g.get('instance_size'),
                'database_username':d['username'],'database_name':d['name'],
                'pooler_mode':g.get('pooler_mode','session'),
                'strict_no_secret_state':False,'ack_sensitive_state':True,
                'explicit_adoption':g['explicit_adoption']}
        if mode == 'adopt_existing':
            (workdir/'import.tf').write_text('import {\n  to = supabase_project.this\n  id = '+json.dumps(g['project_ref'])+'\n}\n')
    (workdir/'terraform.auto.tfvars.json').write_text(json.dumps(tfvars,indent=2)+'\n')
    (workdir/'.gitignore').write_text('*\n!.gitignore\n')
    print('offline_render_complete:'+mode)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('render'); p.add_argument('--resources',required=True); p.add_argument('--workdir',required=True); p.set_defaults(func=render)
    args=parser.parse_args()
    try: args.func(args)
    except (RenderRejected,OSError,yaml.YAMLError):
        print('render_rejected: check nonsecret declaration, lifecycle and state policy',file=sys.stderr)
        return 1
    return 0

if __name__=='__main__': raise SystemExit(main())
