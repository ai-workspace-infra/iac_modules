#!/usr/bin/env python3
"""Read provider-attested candidate SSH identity; never execute host commands."""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse

from unified.auth import request_json
from unified.contracts import ContractError, require, write_json
from unified.hostkeys import console_fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("instance-id", "expected-account", "expected-label", "expected-region", "expected-ip", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--listen-seconds", type=int, default=120)
    args = parser.parse_args()
    require(args.instance_id.isdigit() and 1 <= args.listen_seconds <= 180, "invalid instance or console duration")
    address = ipaddress.ip_address(args.expected_ip)
    require(address.is_global, "public candidate address required")
    output = Path(args.output).resolve()
    require(not output.exists(), "identity evidence path already exists")
    os.umask(0o077)
    output.mkdir(parents=True, mode=0o700)
    headers = {"Authorization": "Bearer " + os.environ["LINODE_TOKEN"], "Content-Type": "application/json"}
    profile = request_json("https://api.linode.com/v4/profile", headers)
    require(profile["username"] == args.expected_account, "provider account differs")
    endpoint = "https://api.linode.com/v4/linode/instances/" + args.instance_id
    live = request_json(endpoint, headers)
    require(live["label"] == args.expected_label and live["region"] == args.expected_region and str(address) in live["ipv4"], "cloud instance identity differs")
    console = request_json(endpoint + "/lish", headers, b"{}")
    url = urlparse(console["weblish_url"])
    require(url.scheme == "wss" and url.hostname == args.expected_region + ".webconsole.linode.com" and not url.username, "untrusted provider console endpoint")
    env = {**os.environ, "NODE_TLS_REJECT_UNAUTHORIZED": "1"}
    env.pop("NODE_OPTIONS", None)
    result = subprocess.run(["node", str(Path(__file__).parent / "lib/akamai-console-read.mjs"), str(args.listen_seconds * 1000)],
        input=json.dumps(console), capture_output=True, text=True, timeout=args.listen_seconds + 15, env=env)
    require(result.returncode == 0, "TLS-verified provider console unavailable")
    (output / "console.txt").write_text(result.stdout)
    try:
        fingerprint = console_fingerprint(result.stdout)
    except ContractError:
        # Never expose the raw terminal or access-bearing console session.
        raise ContractError('complete trusted cloud fingerprint missing; '
            f'decoded_chars={len(result.stdout)}, '
            f'begin_frames={result.stdout.count("IAC_ED25519_FP_BEGIN")}, '
            f'end_frames={result.stdout.count("IAC_ED25519_FP_END")}') from None
    scan = subprocess.run(["ssh-keyscan", "-T", "10", "-t", "ed25519", str(address)], capture_output=True, text=True, timeout=20)
    rows = [line.split() for line in scan.stdout.splitlines() if line and not line.startswith("#")]
    require(len(rows) == 1 and len(rows[0]) == 3 and rows[0][1] == "ssh-ed25519", "one network Ed25519 key required")
    key = base64.b64decode(rows[0][2], validate=True)
    actual = "SHA256:" + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("=")
    require(actual == fingerprint, "network key differs from the complete trusted cloud fingerprint")
    (output / "known_hosts").write_text(str(address) + " ssh-ed25519 " + rows[0][2] + "\n")
    write_json(output / "receipt.json", {"instance_id": args.instance_id, "region": args.expected_region,
        "address": str(address), "ssh_fingerprint": fingerprint, "verified_bits": 256,
        "cloud_identity": True, "console_tls": True, "network_key_matches": True})
    print(json.dumps({"verified_bits": 256, "cloud_identity": True, "network_key_matches": True}))


if __name__ == "__main__":
    main()
