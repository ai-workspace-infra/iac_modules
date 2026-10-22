#!/usr/bin/env python3
"""Read GCP APIs into CMDB envelopes; no database or host operations."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid

from cmdb_observations_v1 import encode_envelope


def now():
    return datetime.now(timezone.utc).isoformat()


class APIError(RuntimeError):
    pass


def request_json(url, headers):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise APIError(f"http_{error.code}") from None
    except (OSError, ValueError):
        raise APIError("transport_or_response_error") from None


def access_token(mode):
    if mode == "metadata":
        result = request_json(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            {"Metadata-Flavor": "Google"},
        )
        return result["access_token"]
    result = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True, timeout=60)
    if result.returncode or not result.stdout.strip():
        raise APIError("identity_unavailable")
    return result.stdout.strip()


def pages(url, headers, fetch=request_json):
    seen = set()
    while True:
        page = fetch(url, headers)
        if not isinstance(page, dict):
            raise APIError("invalid_response")
        yield page
        token = page.get("nextPageToken")
        if not token:
            break
        if token in seen:
            raise APIError("pagination_loop")
        seen.add(token)
        url = url.split("&pageToken=", 1)[0] + "&pageToken=" + urllib.parse.quote(token, safe="")


def compute_observation(item, project, scope):
    zone = item["zone"].rsplit("/", 1)[-1]
    raw = item["status"]
    network = next(iter(item.get("networkInterfaces", [])), {})
    configs = network.get("accessConfigs", [])
    return {
        "provider": "gcp", "account_ref": project, "project_ref": project,
        "resource_kind": "compute",
        "native_resource_id": f"projects/{project}/zones/{zone}/instances/{item['id']}",
        "region": zone.rsplit("-", 1)[0], "scope": scope, "name": item["name"],
        "provider_state": {"RUNNING": "running", "TERMINATED": "stopped", "SUSPENDED": "suspended"}.get(raw, "unknown"),
        "provider_state_raw": raw, "source": "provider_api", "observed_at": now(),
        "public_endpoint": next((c["natIP"] for c in configs if c.get("natIP")), None),
        "private_endpoint": network.get("networkIP"),
        "attributes": {"zone": zone, "machine_type": item.get("machineType", "").rsplit("/", 1)[-1]},
    }


def run_observation(item, project, region, scope):
    condition = item.get("terminalCondition", {})
    state = condition.get("state", "CONDITION_STATE_UNSPECIFIED")
    uid = item.get("uid")
    if not uid:
        raise APIError("missing_service_uid")
    return {
        "provider": "gcp", "account_ref": project, "project_ref": project,
        "resource_kind": "serverless_service",
        "native_resource_id": f"projects/{project}/locations/{region}/services/{uid}",
        "region": region, "scope": scope, "name": item["name"].rsplit("/", 1)[-1],
        "provider_state": {"CONDITION_SUCCEEDED": "ready", "CONDITION_FAILED": "failed", "CONDITION_PENDING": "pending", "CONDITION_RECONCILING": "pending"}.get(state, "unknown"),
        "provider_state_raw": state, "source": "provider_api", "observed_at": now(),
        "public_endpoint": item.get("uri"),
        "attributes": {"service_name": item["name"], "latest_ready_revision": item.get("latestReadyRevision", "")},
    }


def collect(project, scope, kind, region, owner_sha, auth, fetch=request_json):
    run = {
        "run_id": str(uuid.uuid4()), "collector": f"gcp-{kind}", "owner_sha": owner_sha,
        "scope": scope, "account_ref": project, "project_ref": project,
        "region_ref": region if kind == "cloudrun" else "all-zones",
        "resource_kind": "compute" if kind == "compute" else "serverless_service",
        "started_at": now(),
    }
    observations = []
    try:
        headers = {"Authorization": "Bearer " + access_token(auth)}
        if kind == "compute":
            url = f"https://compute.googleapis.com/compute/v1/projects/{project}/aggregated/instances?maxResults=500&returnPartialSuccess=true"
            for page in pages(url, headers, fetch):
                if page.get("unreachables") or page.get("warning", {}).get("code") not in (None, "NO_RESULTS_ON_PAGE"):
                    raise APIError("incomplete_aggregate")
                for group in page.get("items", {}).values():
                    if group.get("warning", {}).get("code") not in (None, "NO_RESULTS_ON_PAGE"):
                        raise APIError("incomplete_zone")
                    observations.extend(compute_observation(item, project, scope) for item in group.get("instances", []))
        else:
            url = f"https://run.googleapis.com/v2/projects/{project}/locations/{region}/services?pageSize=100"
            for page in pages(url, headers, fetch):
                if page.get("unreachable"):
                    raise APIError("incomplete_region")
                observations.extend(run_observation(item, project, region, scope) for item in page.get("services", []))
        run.update(outcome="success", scope_complete=True)
    except (APIError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        run.update(outcome="partial" if observations else "failed", scope_complete=False,
                   error_class=str(error) if isinstance(error, APIError) else "invalid_response_or_identity")
    run["completed_at"] = now()
    return {"schema_version": "cmdb.observations.v1", "run": run, "observations": observations}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--scope", required=True, choices=["shared", "sit", "uat", "prod", "unknown"])
    parser.add_argument("--kind", choices=["compute", "cloudrun"], default="compute")
    parser.add_argument("--region")
    parser.add_argument("--owner-sha", required=True)
    parser.add_argument("--auth", choices=["gcloud", "metadata"], default="metadata")
    args = parser.parse_args()
    if args.kind == "cloudrun" and not args.region:
        parser.error("Cloud Run requires an explicit region allowlist entry")
    if not all(c.isalnum() or c == "-" for c in args.project):
        parser.error("invalid project identifier")
    if args.region and not all(c.isalnum() or c == "-" for c in args.region):
        parser.error("invalid region identifier")
    document = collect(args.project, args.scope, args.kind, args.region, args.owner_sha, args.auth)
    print(encode_envelope(document), end="")
    return 0 if document["run"]["outcome"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
