#!/usr/bin/env python3
"""Enforce terraform-hcl-standard/AGENTS.md section 1: no HCL loops or template control flow."""
import argparse
import re
import sys
from pathlib import Path

_RULES = (
    ("for_each", re.compile(r"^\s*for_each\s*=", re.M)),
    ("count", re.compile(r"^\s*count\s*=", re.M)),
    ("dynamic", re.compile(r'^\s*dynamic\s+"', re.M)),
    ("templatefile", re.compile(r"\btemplatefile\s*\(")),
    ("template-control", re.compile(r"%\{~?\s*(for|if)\b")),
)


def find_violations(text):
    return [name for name, pattern in _RULES if pattern.search(text)]


def check_tree(root):
    problems = []
    for path in sorted([*Path(root).rglob("*.tf"), *Path(root).rglob("*.tf.j2")]):
        if ".terraform" in path.parts:
            continue
        problems.extend((str(path), name) for name in find_violations(path.read_text()))
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+")
    args = parser.parse_args()
    problems = [item for root in args.roots for item in check_tree(root)]
    for path, name in problems:
        print(f"{path}: forbidden HCL construct ({name})", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
