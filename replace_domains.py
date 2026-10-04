import os
from pathlib import Path

base_dir = Path(os.environ.get(
    'GITOPS_ROOT',
    '/Users/shenlan/workspaces/ai-workspace-infra/gitops',
)) / 'resources' / 'svc.plus'
for root, _, files in os.walk(base_dir):
    for f in files:
        if f.endswith('.yaml') or f.endswith('.yml'):
            path = os.path.join(root, f)
            with open(path, 'r') as file:
                content = file.read()
            
            # replace .onwalk.net
            content = content.replace('.onwalk.net', ".{{ env.get('TARGET_DOMAIN_BASE', 'onwalk.net') }}")
            # replace .svc.plus
            content = content.replace('.svc.plus', ".{{ env.get('TARGET_DOMAIN_BASE', 'svc.plus') }}")
            
            with open(path, 'w') as file:
                file.write(content)
