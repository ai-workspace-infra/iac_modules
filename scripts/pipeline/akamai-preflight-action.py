#!/usr/bin/env python3
"""Bind the existing read-only preflight report to exact source and caller identities."""
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

from unified.contracts import checkout_sha, require


def main():
    require(os.environ['PREFLIGHT_ENVIRONMENT'] == 'uat', 'preflight is UAT-only')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,62}', os.environ['PREFLIGHT_ACCOUNT']), 'invalid account')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', os.environ['PREFLIGHT_CORRELATION_ID']), 'invalid correlation')
    require(os.environ['GITHUB_REPOSITORY'] == 'ai-workspace-infra/platform-ops-toolkit', 'invalid controller')
    require(os.environ['GITHUB_WORKFLOW_REF'].startswith(
        'ai-workspace-infra/platform-ops-toolkit/.github/workflows/environment-data-operations.yml@'), 'invalid caller')
    owner_sha = checkout_sha(os.environ['IAC_ROOT'])
    gitops_sha = checkout_sha(os.environ['GITOPS_ROOT'], os.environ['GITOPS_SHA'])
    phase = os.environ.get('PREFLIGHT_PHASE', 'query')
    require(phase in {'validate', 'query'}, 'invalid preflight phase')
    if phase == 'validate':
        return 0
    spec = importlib.util.spec_from_file_location('akamai_preflight', Path(os.environ['IAC_ROOT']) / 'scripts/akamai_state_preflight.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    output = Path(os.environ['PREFLIGHT_JSON_PATH'])
    code = module.main([
        '--environment', 'uat', '--account', os.environ['PREFLIGHT_ACCOUNT'],
        '--correlation-id', os.environ['PREFLIGHT_CORRELATION_ID'],
        '--iac-root', os.environ['IAC_ROOT'], '--gitops-root', os.environ['GITOPS_ROOT'],
        '--output', str(output),
    ])
    report = json.loads(output.read_text())
    report.update(owner_repository='ai-workspace-infra/iac_modules', owner_commit=owner_sha,
                  gitops_commit=gitops_sha, run_id=os.environ['GITHUB_RUN_ID'],
                  run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return code


if __name__ == '__main__':
    sys.exit(main())
