#!/usr/bin/env python3
"""Read non-secret Spec/scope/snapshot on stdin; print reviewable plan only."""
import json,sys
from database_contract import shape,Rejected
from roles_adapter import make_plan

def main():
    try:
        request=json.load(sys.stdin);shape(request,'spec scope snapshot')
        print(json.dumps(make_plan(request['spec'],request['scope'],request['snapshot']).public(),indent=2))
    except (Rejected,ValueError,TypeError,KeyError):
        print('role_plan_rejected',file=sys.stderr);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
