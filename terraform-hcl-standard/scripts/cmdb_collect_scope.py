#!/usr/bin/env python3
"""Consume a GitOps collection scope, save per-scope artifacts, and reconcile inventory."""
import argparse
import json
from pathlib import Path
import re

import yaml

from cmdb_collect_gcp import collect
from cmdb_observations_v1 import SCOPES, encode_envelope, reconcile_observations, validate_envelope


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
        if job["scope"] not in SCOPES:
            raise ValueError("invalid scope")
        jobs.append(job)
    if not jobs:
        raise ValueError("scope contains no enabled collectors")
    return jobs


def _load_structured(path: Path | None):
    if path is None:
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        if "resources" in raw and isinstance(raw["resources"], (dict, list)):
            return raw["resources"]
        if "resource_index" in raw and isinstance(raw["resource_index"], dict):
            return raw["resource_index"]
    return raw


def execute_scope_jobs(
    jobs,
    output_dir: Path,
    owner_sha: str,
    auth: str = "metadata",
    *,
    collector_fn=collect,
    desired_resources=None,
    prior_resources=None,
    report_path: Path | None = None,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    envelopes = []
    for job in jobs:
        envelope = collector_fn(
            job["project"],
            job["scope"],
            job["kind"],
            job.get("region"),
            owner_sha,
            auth,
        )
        validated = validate_envelope(envelope)
        envelopes.append(validated)
        path = output_dir / (job["name"] + ".json")
        path.write_text(encode_envelope(validated), encoding="utf-8")
        run = validated["run"]
        summaries.append(
            {
                "name": job["name"],
                "run_id": run["run_id"],
                "outcome": run["outcome"],
                "scope_complete": run["scope_complete"],
                "observations": len(validated["observations"]),
                "started_at": run["started_at"],
                "completed_at": run["completed_at"],
                "error_class": run.get("error_class"),
            }
        )

    report = reconcile_observations(
        envelopes,
        desired_resources=desired_resources,
        prior_resources=prior_resources,
    )
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return summaries, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--owner-sha", required=True)
    parser.add_argument("--auth", choices=["gcloud", "metadata"], default="metadata")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--desired-file", type=Path, help="Optional desired resources YAML/JSON for reconciliation")
    parser.add_argument("--prior-state", type=Path, help="Optional prior reconciliation/CMDB state JSON")
    parser.add_argument("--reconciliation-report", type=Path, help="Optional path to write reconciliation report JSON")
    args = parser.parse_args()
    jobs = load_jobs(args.scope_file)
    if not re.fullmatch(r"[a-f0-9]{40}", args.owner_sha):
        parser.error("owner-sha must be an immutable full commit")
    if args.validate_only:
        print(json.dumps({"validated_collectors": len(jobs)}))
        return 0
    summaries, _ = execute_scope_jobs(
        jobs,
        args.output_dir,
        args.owner_sha,
        args.auth,
        desired_resources=_load_structured(args.desired_file),
        prior_resources=_load_structured(args.prior_state),
        report_path=args.reconciliation_report,
    )
    print(json.dumps(summaries, indent=2))
    return 0 if all(item["outcome"] == "success" for item in summaries) else 2


if __name__ == "__main__":
    raise SystemExit(main())
