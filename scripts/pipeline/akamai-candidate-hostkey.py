#!/usr/bin/env python3
"""Bind existing provider console attestation to an exact owner CMDB artifact."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from unified.contracts import require


def select(path, checksum, node):
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == checksum, "candidate CMDB checksum differs")
    data = json.loads(raw)
    require(isinstance(data, dict) and len(data) == 1, "one candidate is required")
    facts = next(iter(data.values()))
    require(facts.get("name") == node and facts.get("label") == node, "candidate node identity differs")
    require(str(facts.get("instance_id", "")).isdigit(), "candidate instance ID missing")
    require(facts.get("host_vars", {}).get("cloud_provider") == "akamai-cloud", "candidate provider differs")
    return facts


def main():
    facts = select(os.environ['CANDIDATE_CMDB'], os.environ['CANDIDATE_CMDB_SHA256'], os.environ['CANDIDATE_NODE'])
    subprocess.run([sys.executable, str(Path(__file__).with_name('akamai-hostkey-read.py')),
        '--instance-id', str(facts['instance_id']), '--expected-account', os.environ['CANDIDATE_ACCOUNT'],
        '--expected-label', facts['label'], '--expected-region', facts['region'], '--expected-ip', facts['ip'],
        '--output', os.environ['CANDIDATE_OUTPUT']], check=True)


if __name__ == '__main__':
    main()
