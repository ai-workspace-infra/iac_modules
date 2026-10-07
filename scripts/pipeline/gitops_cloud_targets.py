#!/usr/bin/env python3
"""Read and validate provider target identity from a pinned GitOps checkout."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml


PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
GCP_REGION = re.compile(r"^[a-z]+-[a-z]+[0-9]+$")
AWS_REGION = re.compile(r"^[a-z]+-[a-z]+-[0-9]+$")
ACCOUNT = re.compile(r"^[0-9]{12}$")
ROLE = re.compile(r"^[A-Za-z0-9+=,.@_-]+$")


def document(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("GitOps declaration must be a mapping")
    return value


def output(values: dict[str, str], path: Path | None) -> None:
    if path:
        with path.open("a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")


def gcp(args: argparse.Namespace) -> None:
    global_config = document(args.manifest).get("global")
    if not isinstance(global_config, dict):
        raise ValueError("GCP GitOps manifest must contain a global mapping")
    project_id = str(global_config.get("project_id", ""))
    region = str(global_config.get("region", ""))
    if not PROJECT.fullmatch(project_id):
        raise ValueError("GitOps GCP project_id is empty or malformed")
    if not GCP_REGION.fullmatch(region):
        raise ValueError("GitOps GCP region is empty or malformed")
    if args.mode == "validate":
        environment = str(global_config.get("environment", ""))
        registry = str(global_config.get("artifact_registry_location", ""))
        if environment != args.environment:
            raise ValueError(f"GCP manifest environment mismatch: expected {args.environment}, found {environment}")
        if project_id != args.project_id:
            raise ValueError(f"resolved GCP project does not match GitOps: expected {project_id}, found {args.project_id}")
        if region != args.region:
            raise ValueError(f"resolved GCP region does not match GitOps: expected {region}, found {args.region}")
        if registry != region:
            raise ValueError("GitOps Artifact Registry location must match the declared GCP region")
    output({"project_id": project_id, "region": region}, args.github_output)
    print(f"GCP GitOps target {args.mode}: project={project_id}, region={region}")


def aws(args: argparse.Namespace) -> None:
    value = document(args.manifest)
    expected_repository = "ai-workspace-infra/platform-ops-toolkit"
    if args.environment == "prod":
        required_tag = f"repo:{expected_repository}:ref:refs/tags/v*"
        required_environment = f"repo:{expected_repository}:environment:production"
    elif args.environment == "uat":
        required_tag = f"repo:{expected_repository}:ref:refs/tags/uat-daily-build-*"
        required_environment = f"repo:{expected_repository}:environment:uat"
    else:
        raise ValueError(f"unsupported AWS OIDC deployment environment: {args.environment}")
    spec = value.get("spec") if isinstance(value.get("spec"), dict) else {}
    cloud = spec.get("aws") if isinstance(spec.get("aws"), dict) else {}
    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    account = str(cloud.get("account_id", ""))
    region = str(cloud.get("region", ""))
    role_name = str(cloud.get("role_name", ""))
    role_arn = str(cloud.get("role_arn", ""))
    audience = str(spec.get("audience", ""))
    subjects = spec.get("subjects")
    required_subjects = {
        f"repo:{expected_repository}:ref:refs/heads/main",
        required_tag,
        required_environment,
    }
    valid = (
        value.get("apiVersion") == "gitops.svc.plus/v1alpha1"
        and value.get("kind") == "GitHubActionsOIDCConfig"
        and metadata.get("environment") == args.environment
        and metadata.get("provider") == "aws"
        and spec.get("provider_url") == "https://token.actions.githubusercontent.com"
        and audience == "sts.amazonaws.com"
        and ACCOUNT.fullmatch(account)
        and account == args.account
        and AWS_REGION.fullmatch(region)
        and ROLE.fullmatch(role_name)
        and role_arn == f"arn:aws:iam::{account}:role/{role_name}"
        and isinstance(subjects, list)
        and required_subjects.issubset(set(subjects))
    )
    if not valid:
        raise ValueError(f"GitOps AWS OIDC declaration failed the {args.environment} trust contract")
    output({"role_arn": role_arn, "region": region, "audience": audience}, args.github_output)
    print(f"AWS OIDC GitOps target validated for {args.environment}; no credentials were read")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="provider", required=True)
    gcp_parser = subparsers.add_parser("gcp")
    gcp_parser.add_argument("--manifest", type=Path, required=True)
    gcp_parser.add_argument("--mode", choices=("read", "validate"), required=True)
    gcp_parser.add_argument("--environment", default="")
    gcp_parser.add_argument("--project-id", default="")
    gcp_parser.add_argument("--region", default="")
    gcp_parser.add_argument("--github-output", type=Path)
    aws_parser = subparsers.add_parser("aws")
    aws_parser.add_argument("--manifest", type=Path, required=True)
    aws_parser.add_argument("--environment", required=True)
    aws_parser.add_argument("--account", required=True)
    aws_parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        (gcp if args.provider == "gcp" else aws)(args)
    except (KeyError, TypeError, ValueError, yaml.YAMLError) as error:
        raise SystemExit(f"cloud target contract: {error}") from None


if __name__ == "__main__":
    main()
