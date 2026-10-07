#!/usr/bin/env python3
"""Immutable domain declaration adapter and sanitized owner-operation evidence."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import yaml

from unified.contracts import checkout_sha, require, source_file


def main():
    environment = os.environ['REQUESTED_ENVIRONMENT']
    require(environment in {'sit', 'uat', 'prod'}, 'unsupported environment')
    require(re.fullmatch(r'(v|daily-build-)[0-9][A-Za-z0-9._-]*', os.environ['RELEASE_REF']), 'immutable release required')
    phase = os.environ['DOMAIN_PHASE']
    require(phase in {'prepare', 'receipt'}, 'invalid domain phase')
    owner = checkout_sha(os.environ['IAC_ROOT'])
    head = checkout_sha(os.environ['GITOPS_DIR'], os.environ['GITOPS_REF'])
    source = source_file(os.environ['GITOPS_DIR'], f'topology/{environment}/serverless/runtime-topology.yaml')
    config = yaml.safe_load(source.read_text())
    spec = importlib.util.spec_from_file_location('domains_request', Path(__file__).with_name('validate-serverless-domains-request.py'))
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    validator.validate(config, environment, os.environ['SERVERLESS_DNS_MODE'], head, head,
                       os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_WORKFLOW_REF'])
    if environment == 'prod':
        subprocess.run(['git', '-C', os.environ['GITOPS_DIR'], 'merge-base', '--is-ancestor', head, 'origin/main'], check=True)
    output = Path(os.environ['CLOUDFLARE_BOUNDARY_CONFIG'])
    if phase == 'prepare':
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(config, indent=2) + '\n')
    else:
        require(json.loads(output.read_text()) == config, 'executed domain declaration differs from fixed GitOps')
        receipt = Path(os.environ['DOMAIN_RECEIPT_FILE'])
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(dict(
            schema=1, accepted=True, scope='provider-operation',
            owner_repository='ai-workspace-infra/iac_modules', owner_commit=owner,
            run_id=os.environ['GITHUB_RUN_ID'], run_attempt=os.environ['GITHUB_RUN_ATTEMPT'],
            environment=environment, release_ref=os.environ['RELEASE_REF'], gitops_commit=head,
            operation='domains', target=os.environ['SERVERLESS_DNS_MODE'],
        ), indent=2) + '\n')


if __name__ == '__main__':
    main()
