#!/usr/bin/env python3
"""Detect credential-shaped content so it never reaches Git, YAML, tfvars, HCL, CMDB or logs."""
import argparse
import re
import sys
from pathlib import Path

SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "df-api-key",
        "opt_set",
        "password",
        "secret",
        "token",
        "webhook",
        "workspace_token",
    }
)

_PATTERNS = {
    "vault-token": re.compile(r"\bhv[sbr]\.[A-Za-z0-9_-]{20,}"),
    "bearer-token": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    "token-query": re.compile(r"(?i)[?&](access_token|api_key|apikey|key|token|secret)=[^&\s\"']{8,}"),
    "chat-webhook": re.compile(
        r"(?i)(hooks\.slack\.com/services/|oapi\.dingtalk\.com/robot/send|open\.feishu\.cn/open-apis/bot/"
        r"|qyapi\.weixin\.qq\.com/cgi-bin/webhook/send|api\.telegram\.org/bot\d)"
    ),
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "aws-access-key": re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
}


def scan_text(text):
    """Return the names of credential patterns found in ``text`` (never the matches)."""
    return sorted(name for name, pattern in _PATTERNS.items() if pattern.search(text))


def scan_keys(value, path="$"):
    """Return paths of mapping keys that would hold credentials."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                found.append(f"{path}.{key}")
            found.extend(scan_keys(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(scan_keys(item, f"{path}[{index}]"))
    return found


def scan_tree(root, skip_dirs=(".terraform", ".git", "__pycache__")):
    """Scan files below ``root``; report ``(relative path, pattern)`` without echoing content."""
    findings = []
    root = Path(root)
    files = [root] if root.is_file() else sorted(root.rglob("*"))
    for path in files:
        if not path.is_file() or any(part in skip_dirs for part in path.relative_to(root.parent if root.is_file() else root).parts):
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for name in scan_text(text):
            findings.append((path.name if root.is_file() else str(path.relative_to(root)), name))
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    findings = []
    for item in args.paths:
        findings.extend(scan_tree(item))
    for file, name in findings:
        print(f"credential-shaped content ({name}) in {file}", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
