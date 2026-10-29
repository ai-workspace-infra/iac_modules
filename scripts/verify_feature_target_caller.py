#!/usr/bin/env python3
"""Require the protected Feature caller before obtaining provider credentials."""
import os
import re
import sys


def validate(env):
    repo = env.get('GITHUB_REPOSITORY', '')
    if repo not in ('ai-workspace-infra/Platform-Orchestrator', 'ai-workspace-infra/platform-ops-toolkit'):
        raise ValueError('unsupported caller repository')
    if (env.get('GITHUB_REF') != 'refs/heads/main' or
        env.get('GITHUB_WORKFLOW_REF') != repo + '/.github/workflows/feature-lane-deploy.yml@refs/heads/main' or
        not re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', '')) or
        not re.fullmatch(r'[1-9][0-9]*', env.get('GITHUB_RUN_ID', '')) or
        not re.fullmatch(r'[1-9][0-9]*', env.get('GITHUB_RUN_ATTEMPT', ''))):
        raise ValueError('protected Main caller required')


if __name__ == '__main__':
    try:
        validate(os.environ)
    except ValueError:
        print('::error::Unapproved Feature target caller', file=sys.stderr)
        sys.exit(1)
