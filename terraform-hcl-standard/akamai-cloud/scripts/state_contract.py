#!/usr/bin/env python3
"""Canonical Akamai Cloud Terraform state namespace contract."""

from __future__ import annotations

import argparse
import re


CLOUD = "akamai-cloud"
UAT_NAMESPACES = (
    "web-saas",
    "open-platform",
    "ai-workspace",
    "agent-proxy-jp",
    "agent-proxy-us",
    "agent-proxy-sg",
)
PERSISTENT_NAMESPACES = frozenset({"open-platform"})
CLEANUP_NAMESPACES = tuple(
    namespace for namespace in UAT_NAMESPACES if namespace not in PERSISTENT_NAMESPACES
)
FORBIDDEN_SHARED_NAMESPACES = frozenset({"selfhost", "all", "default", "shared"})
FORBIDDEN_ACCOUNT_ALIASES = frozenset({"primary", "default", "main"})
COMPONENT_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")


def validate_component(name: str, value: str) -> str:
    value = str(value or "").strip().lower()
    if not value or not COMPONENT_RE.fullmatch(value):
        raise ValueError(f"{name} must match {COMPONENT_RE.pattern}: {value!r}")
    return value


def validate_namespace(namespace: str, *, environment: str = "uat") -> str:
    namespace = validate_component("namespace", namespace)
    if namespace in FORBIDDEN_SHARED_NAMESPACES:
        raise ValueError(f"shared Terraform namespace is forbidden: {namespace}")
    if environment == "uat" and namespace not in UAT_NAMESPACES:
        allowed = ", ".join(UAT_NAMESPACES)
        raise ValueError(f"unsupported Akamai UAT namespace {namespace!r}; expected one of: {allowed}")
    return namespace


def canonical_state_key(
    *, environment: str, project: str, account: str, namespace: str
) -> str:
    environment = validate_component("environment", environment)
    project = validate_component("project", project)
    account = validate_component("account", account)
    if account in FORBIDDEN_ACCOUNT_ALIASES:
        raise ValueError(f"account must be the concrete Akamai account name, not {account!r}")
    namespace = validate_namespace(namespace, environment=environment)
    return (
        f"terraform/{environment}/{project}/{CLOUD}/{account}/"
        f"{namespace}/terraform.tfstate"
    )


def may_destroy(namespace: str) -> bool:
    """Return whether routine post-acceptance cleanup may destroy a namespace."""
    return validate_namespace(namespace) in CLEANUP_NAMESPACES


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default="uat")
    parser.add_argument("--project", default="svc.plus")
    parser.add_argument("--account", required=True)
    parser.add_argument("--namespace", required=True)
    args = parser.parse_args()
    print(
        canonical_state_key(
            environment=args.environment,
            project=args.project,
            account=args.account,
            namespace=args.namespace,
        )
    )


if __name__ == "__main__":
    main()
