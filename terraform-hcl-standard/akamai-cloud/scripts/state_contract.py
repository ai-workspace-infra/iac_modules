#!/usr/bin/env python3
"""Akamai adapter for the provider-neutral state identity contract."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from iac_identity import validate_namespace, canonical_state_key as _canonical_state_key

def canonical_state_key(*, environment, project, account, namespace):
    return _canonical_state_key(environment=environment, project=project, provider="akamai-cloud", account=account, namespace=namespace)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("environment", "project", "account", "namespace"):
        parser.add_argument("--" + name, required=True)
    print(canonical_state_key(**vars(parser.parse_args())))

if __name__ == "__main__":
    main()
