#!/usr/bin/env python3
"""Validate protected same-run Toolkit DNS intent and fresh IaC CMDB evidence."""
import hashlib
import ipaddress
import json
import os
import re
import sys
from pathlib import Path


def require(ok, message):
    if not ok:
        raise ValueError(message)


def domains(feature_id):
    require(re.fullmatch(r"feature-[a-z][a-z0-9-]{1,48}", feature_id) is not None,
            "invalid Feature ID")
    slug = feature_id.removeprefix("feature-")
    return {"console": f"{slug}-sit.onwalk.net",
            "accounts": f"accounts-{slug}-sit.onwalk.net",
            "billing": f"billing-{slug}-sit.onwalk.net"}


def verify():
    request_path, cmdb_path = Path(os.environ["REQUEST_PATH"]), Path(os.environ["CMDB_PATH"])
    request_raw, cmdb_raw = request_path.read_bytes(), cmdb_path.read_bytes()
    require(hashlib.sha256(request_raw).hexdigest() == os.environ["REQUEST_SHA256"], "request checksum mismatch")
    require(hashlib.sha256(cmdb_raw).hexdigest() == os.environ["CMDB_SHA256"], "CMDB checksum mismatch")
    request, cmdb = json.loads(request_raw), json.loads(cmdb_raw)
    require(request.get("schema_version") == "sit-feature-dns-request/v1" and
            request.get("result") == "verified" and request.get("environment") == "sit",
            "verified SIT Feature DNS request required")
    feature_id = request.get("feature_id", "")
    expected_domains = domains(feature_id)
    require(request.get("namespace") == f"{feature_id}-sit" and request.get("domains") == expected_domains,
            "Feature ID namespace/domain mapping mismatch")
    require(request.get("request_artifact") == os.environ["REQUEST_ARTIFACT"], "request artifact name mismatch")
    require(request.get("cmdb_artifact") == os.environ["CMDB_ARTIFACT"] and
            request.get("cmdb_sha256") == os.environ["CMDB_SHA256"], "request CMDB binding mismatch")
    require(request.get("instance_id") == os.environ["INSTANCE_ID"], "request target instance mismatch")
    require(request.get("gitops_sha") == os.environ["GITOPS_SHA"] and
            re.fullmatch(r"[0-9a-f]{40}", request.get("gitops_sha", "")), "candidate SHA mismatch")
    require(request.get("candidate_sha256") == os.environ["CANDIDATE_SHA256"] and
            re.fullmatch(r"[0-9a-f]{64}", request.get("candidate_sha256", "")), "candidate receipt digest mismatch")
    source = request.get("source", {})
    require(source.get("workflow_ref") == "ai-workspace-infra/platform-ops-toolkit/.github/workflows/dev-feature-deploy.yml@refs/heads/main" and
            str(source.get("run_id")) == os.environ["GITHUB_RUN_ID"] and
            str(source.get("run_attempt")) == os.environ["GITHUB_RUN_ATTEMPT"], "request is not from this protected Toolkit run")
    node = cmdb.get("dev-k3s-v5", {})
    require({"dev", "k3s", "k3s_server", "akamai_cloud"}.issubset(set(node.get("groups", []))), "CMDB target group mismatch")
    address = ipaddress.IPv4Address(node.get("ip", ""))
    require(address.is_global, "CMDB target is not a public IPv4")
    return {"feature_id": feature_id, "namespace": request["namespace"], "domains": expected_domains,
            "target_ip": str(address), "instance_id": request["instance_id"]}


if __name__ == "__main__":
    try:
        print(json.dumps(verify(), sort_keys=True))
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"::error::{error}", file=sys.stderr)
        raise SystemExit(1)
