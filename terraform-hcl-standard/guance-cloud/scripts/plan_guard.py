#!/usr/bin/env python3
"""Gate a Terraform plan (``terraform show -json``) and emit a value-free summary.

The plan JSON contains planned attribute values, including sensitive ones, so it must
only be piped through this script and never stored or uploaded. The summary lists
addresses and actions only.
"""
import argparse
import json
import sys

NOOP = {"no-op", "read"}


def summarize(plan):
    changes = []
    for change in plan.get("resource_changes", []):
        actions = tuple(change["change"]["actions"])
        changes.append(
            {
                "address": change["address"],
                "actions": list(actions),
                "importing": bool(change["change"].get("importing")),
            }
        )
    return changes


def evaluate(changes, *, expect_no_changes=False, allow_import_updates=False, allow_delete=()):
    problems = []
    for item in changes:
        actions = set(item["actions"])
        if "delete" in actions and item["address"] not in allow_delete:
            problems.append(f"{item['address']}: {'replace' if 'create' in actions else 'delete'} is not allowed")
        elif item["importing"] and actions - NOOP and not allow_import_updates:
            problems.append(f"{item['address']}: imported object differs from declaration; review before applying")
        elif expect_no_changes and actions - NOOP:
            problems.append(f"{item['address']}: unexpected {'/'.join(item['actions'])}")
        if expect_no_changes and item["importing"]:
            problems.append(f"{item['address']}: pending import in a plan expected to be empty")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", default="-", help="plan JSON file, default stdin")
    parser.add_argument("--expect-no-changes", action="store_true")
    parser.add_argument("--allow-import-updates", action="store_true")
    parser.add_argument("--allow-delete", action="append", default=[], metavar="ADDRESS")
    args = parser.parse_args()
    raw = sys.stdin.read() if args.plan == "-" else open(args.plan).read()
    changes = summarize(json.loads(raw))
    problems = evaluate(
        changes,
        expect_no_changes=args.expect_no_changes,
        allow_import_updates=args.allow_import_updates,
        allow_delete=set(args.allow_delete),
    )
    counts = {}
    for item in changes:
        key = "+".join(item["actions"])
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps({"counts": counts, "imports": sum(i["importing"] for i in changes), "changes": [c for c in changes if set(c["actions"]) - NOOP or c["importing"]], "problems": problems}, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
