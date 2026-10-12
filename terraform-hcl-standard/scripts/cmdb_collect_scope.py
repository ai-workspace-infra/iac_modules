#!/usr/bin/env python3
"""Consume a GitOps collection scope and save sanitized per-scope artifacts."""
import argparse
import json
from pathlib import Path
import re

import yaml

from cmdb_collect_gcp import collect
from cmdb_observations_v1 import encode_envelope


def load_jobs(path):
    document = yaml.safe_load(path.read_text())
    if document.get("apiVersion") != "inventory.svc.plus/v1" or document.get("kind") != "CMDBCollectionScope":
        raise ValueError("unsupported GitOps collection scope")
    names = set()
    jobs = []
    for job in document["spec"]["collectors"]:
        if not job.get("enabled", False):
            continue
        if not re.fullmatch(r"[a-z0-9-]+", job["name"]) or job["name"] in names:
            raise ValueError("invalid or duplicate collector name")
        names.add(job["name"])
        if job["provider"] != "gcp" or job["kind"] not in ("compute", "cloudrun"):
            raise ValueError("collector adapter is unavailable")
        if job["kind"] == "cloudrun" and not job.get("region"):
            raise ValueError("Cloud Run requires an explicit region")
        if not re.fullmatch(r"[a-z0-9-]+", job["project"]):
            raise ValueError("invalid project")
        if job.get("region") and not re.fullmatch(r"[a-z0-9-]+", job["region"]):
            raise ValueError("invalid region")
        if job["scope"] not in ("shared", "sit", "uat", "prod", "unknown"):
            raise ValueError("invalid scope")
        jobs.append(job)
    if not jobs:
        raise ValueError("scope contains no enabled collectors")
    return jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--owner-sha", required=True)
    parser.add_argument("--auth", choices=["gcloud", "metadata"], default="metadata")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    jobs = load_jobs(args.scope_file)
    if not re.fullmatch(r"[a-f0-9]{40}", args.owner_sha):
        parser.error("owner-sha must be an immutable full commit")
    if args.validate_only:
        print(json.dumps({"validated_collectors": len(jobs)}))
        return 0
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    for job in jobs:
        envelope = collect(job["project"], job["scope"], job["kind"], job.get("region"), args.owner_sha, args.auth)
        path = args.output_dir / (job["name"] + ".json")
        path.write_text(encode_envelope(envelope))
        run = envelope["run"]
        summaries.append({"name": job["name"], "run_id": run["run_id"], "outcome": run["outcome"], "scope_complete": run["scope_complete"], "observations": len(envelope["observations"]), "error_class": run.get("error_class")})
    print(json.dumps(summaries, indent=2))
    return 0 if all(item["outcome"] == "success" for item in summaries) else 2


if __name__ == "__main__":
    raise SystemExit(main())
