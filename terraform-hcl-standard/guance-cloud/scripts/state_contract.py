#!/usr/bin/env python3
"""Canonical Terraform state key for Guance, following docs/howto/unified-iac-state-contract.md.

    terraform/<environment>/<project>/<cloud>/<account>/<workspace>/terraform.tfstate

``account`` is the concrete Guance workspace alias (never primary/default/main) and
``workspace`` is the Terraform namespace that separates state within it.
"""
import argparse
import re

CLOUD = "guance-cloud"
NAMESPACE = "observability"
FORBIDDEN_ACCOUNT_ALIASES = frozenset({"primary", "default", "main"})
FORBIDDEN_NAMESPACES = frozenset({"selfhost", "all", "default", "shared"})
COMPONENT_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")


def _component(name, value):
    value = str(value or "").strip().lower()
    if not COMPONENT_RE.fullmatch(value):
        raise ValueError(f"{name} must match {COMPONENT_RE.pattern}: {value!r}")
    return value


def canonical_state_key(*, environment, project, account, namespace=NAMESPACE):
    environment = _component("environment", environment)
    project = _component("project", project)
    account = _component("account", account)
    namespace = _component("namespace", namespace)
    if account in FORBIDDEN_ACCOUNT_ALIASES:
        raise ValueError(f"account must be the concrete Guance workspace alias, not {account!r}")
    if namespace in FORBIDDEN_NAMESPACES:
        raise ValueError(f"shared Terraform namespace is forbidden: {namespace}")
    return f"terraform/{environment}/{project}/{CLOUD}/{account}/{namespace}/terraform.tfstate"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default="uat")
    parser.add_argument("--project", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--namespace", default=NAMESPACE)
    args = parser.parse_args()
    print(canonical_state_key(environment=args.environment, project=args.project, account=args.account, namespace=args.namespace))


if __name__ == "__main__":
    main()
