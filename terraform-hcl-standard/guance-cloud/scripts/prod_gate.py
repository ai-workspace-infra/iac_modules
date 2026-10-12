#!/usr/bin/env python3
"""PROD promotion gate (#431): verify a signed-off acceptance record before any PROD apply.

The gate only reads a JSON record; it never contacts Guance, Vault or Terraform. A PROD apply
workflow must call it and stop on a non-zero exit. Offline-only evidence never satisfies it.
"""
import argparse
import json
import re
import sys
from datetime import datetime

from state_contract import canonical_state_key

# gate id -> issue that defines the acceptance (UAT results must be live, not offline).
UAT_GATES = {
    "vault_kv_and_oidc": "#425 per-purpose records, exact policies, UAT cannot read PROD, no credential echo",
    "dashboard_render_and_apply": "#426 render/fmt/validate/inventory plus real UAT apply and CMDB UUIDs",
    "remote_state_and_stable_plan": "#427 unified remote state, import, second plan without unexpected diff",
    "notify_and_alert_policy": "#428 test-only receiver, firing and recovery notifications, no webhook leakage",
    "monitors_and_mute": "#429 three monitors on measured baselines, failure/recovery, mute expiry, drift detection",
    "ci_and_grafana_fallback": "#430 CI post-release verification and Grafana healthy with Guance disabled",
    "cost_and_quota": "free-tier or commercial quota, retention and cost reviewed for PROD volume",
    "rollback_rehearsed": "GitOps revert -> render -> plan -> apply rehearsed in UAT",
}
EVIDENCE_REQUIRED = {"status", "verified_at", "verified_by", "evidence"}
URL_RE = re.compile(r"^https://github\.com/ai-workspace-infra/[A-Za-z0-9._-]+/(issues|pull|actions/runs)/[0-9]+")


def _date(value):
    try:
        datetime.strptime(str(value), "%Y-%m-%d")
        return True
    except ValueError:
        return False


def evaluate(record):
    problems = []
    gates = record.get("uat_acceptance", {})
    for gate, meaning in UAT_GATES.items():
        entry = gates.get(gate)
        if not isinstance(entry, dict) or not EVIDENCE_REQUIRED <= set(entry):
            problems.append(f"uat_acceptance.{gate}: missing evidence ({meaning})")
        elif entry["status"] != "verified":
            problems.append(f"uat_acceptance.{gate}: status is {entry['status']!r}, not 'verified'")
        elif not _date(entry["verified_at"]) or not URL_RE.match(str(entry["evidence"])):
            problems.append(f"uat_acceptance.{gate}: needs YYYY-MM-DD date and a GitHub issue/PR/run URL as evidence")

    prod = record.get("prod", {})
    uat = record.get("uat", {})
    for field in ("workspace_alias", "project", "management_credential_id", "state_key"):
        if not prod.get(field) or not uat.get(field):
            problems.append(f"prod/uat.{field}: required to prove isolation")
    if prod.get("workspace_alias") and prod["workspace_alias"] == uat.get("workspace_alias"):
        problems.append("prod must use its own workspace, not the UAT workspace")
    if prod.get("management_credential_id") and prod["management_credential_id"] == uat.get("management_credential_id"):
        problems.append("prod must use its own management credential")
    if prod.get("workspace_alias") and prod.get("project"):
        try:
            expected = canonical_state_key(environment="prod", project=prod["project"], account=prod["workspace_alias"])
        except ValueError as error:
            problems.append(f"prod identity is invalid: {error}")
        else:
            if prod.get("state_key") != expected:
                problems.append(f"prod state_key must be {expected}")
        if uat.get("state_key") == prod.get("state_key"):
            problems.append("prod must not share the UAT state key")

    review = record.get("prod_plan_review", {})
    if not (review.get("reviewed_by") and review.get("no_delete_or_replace") is True and review.get("plan_run")):
        problems.append("prod_plan_review: needs reviewed_by, plan_run and no_delete_or_replace=true")
    elif review["reviewed_by"] == record.get("requested_by"):
        problems.append("prod_plan_review: reviewer must differ from the requester")

    auth = record.get("authorization", {})
    if not (auth.get("approved_by") and _date(auth.get("approved_at", "")) and URL_RE.match(str(auth.get("issue_url", ""))) and auth.get("scope") == "prod-apply"):
        problems.append("authorization: explicit approval (approved_by, approved_at, issue_url, scope='prod-apply') is required")
    elif auth["approved_by"] == record.get("requested_by"):
        problems.append("authorization: approver must differ from the requester")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True)
    args = parser.parse_args()
    with open(args.record) as handle:
        problems = evaluate(json.load(handle))
    for problem in problems:
        print(f"BLOCKED: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("PROD gate satisfied (the record is evidence of sign-off, not a deployment).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
