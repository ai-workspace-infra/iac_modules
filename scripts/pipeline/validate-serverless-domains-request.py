#!/usr/bin/env python3
"""Nonsecret reusable-workflow request validation before provider credentials."""
import json
import os
from pathlib import Path
import re
import subprocess


def validate(config, environment, dns_mode, gitops_ref, gitops_head, repository, workflow_ref):
    if repository != 'ai-workspace-infra/platform-ops-toolkit' or not workflow_ref.startswith(
            repository + '/.github/workflows/serverless-orchestrator.yml@'):
        raise ValueError('Only the reviewed Toolkit Serverless controller may call this owner')
    if not re.fullmatch(r'[0-9a-f]{40}', gitops_ref) or gitops_head != gitops_ref:
        raise ValueError('Exact GitOps commit required')
    if environment not in {'sit', 'uat', 'prod'} or config.get('kind') != 'EdgeRoutingConfig':
        raise ValueError('Unsupported environment or declaration')
    if config['metadata']['environment'] != environment:
        raise ValueError('Declaration environment mismatch')
    if config['metadata']['mode'] != 'serverless' or config['spec']['runtime']['mode'] != 'serverless':
        raise ValueError('Only the Serverless domain publisher is in scope')
    allowed = {'none', 'prod-cutover'} if environment == 'prod' else {'none', 'uat-records'}
    if dns_mode not in allowed:
        raise ValueError('DNS scope does not match the requested environment')


def main():
    config = json.loads(Path(os.environ['CLOUDFLARE_BOUNDARY_CONFIG']).read_text())
    directory = os.environ['GITOPS_DIR']
    head = subprocess.check_output(['git', '-C', directory, 'rev-parse', 'HEAD'], text=True).strip()
    validate(config, os.environ['REQUESTED_ENVIRONMENT'], os.environ['SERVERLESS_DNS_MODE'],
             os.environ['GITOPS_REF'], head, os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_WORKFLOW_REF'])
    if os.environ['REQUESTED_ENVIRONMENT'] == 'prod':
        subprocess.run(['git', '-C', directory, 'merge-base', '--is-ancestor', head, 'origin/main'], check=True)
    print('Fixed declaration and caller validated; stable GTM API aliases remain owned by Edge Gateway')


if __name__ == '__main__':
    main()
