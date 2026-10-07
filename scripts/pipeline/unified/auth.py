"""Provider identity and prerequisite reads; Vault secrets remain job-local."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .contracts import ContractError, output, require, write_json


def request_json(url, headers=None, data=None, method=None):
    req = urllib.request.Request(url, headers=headers or {}, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise ContractError(f"remote API refused request (HTTP {error.code})") from None


def command_json(command):
    result = subprocess.run(command, capture_output=True, text=True)
    require(result.returncode == 0, f"provider read failed: {command[0]}")
    return json.loads(result.stdout)


def export_env(key, value, secret=True):
    require("\n" not in str(value) and "\r" not in str(value), "multiline environment export rejected")
    if secret:
        print(f"::add-mask::{value}")
    if os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"], "a") as stream:
            stream.write(f"{key}={value}\n")
    os.environ[key] = str(value)


def vault_session(role):
    jwt = request_json(os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=vault",
                       {"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]})["value"]
    result = request_json("https://vault.svc.plus/v1/auth/jwt/login", {"Content-Type": "application/json"},
                          json.dumps({"role": role, "jwt": jwt}).encode())
    require(0 < result["auth"].get("lease_duration", 0) <= 1200, "Vault session must have a bounded lifetime")
    return result["auth"]


def load_credentials(context, target, stage, private_dir):
    auth = target["auth"]
    bootstrap = stage == "bootstrap" and context["bootstrap_mode"] == "reconcile"
    role = auth.get("bootstrap_vault_role" if bootstrap else "vault_role")
    require(role and role.startswith(f"github-actions-platform-ops-toolkit-{target['environment']}"), "Vault role must bind target environment")
    session = vault_session(role)
    token = session["client_token"]
    private_dir = Path(private_dir)
    private_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(private_dir, 0o700)
    (private_dir / "vault-token").write_text(token)
    os.chmod(private_dir / "vault-token", 0o600)
    write_json(private_dir / "vault-session.json", {"token_type": session.get("token_type"), "lease_duration": session.get("lease_duration")})

    def read(path):
        require(path.startswith("kv/data/") and ".." not in path and "\n" not in path, "invalid Vault record reference")
        return request_json("https://vault.svc.plus/v1/" + path, {"X-Vault-Token": token})["data"]["data"]

    state = read(auth.get("state_record", f"kv/data/CICD/{target['environment']}/iac_state"))
    for key in ("TF_STATE_ENDPOINT", "TF_STATE_BUCKET", "TF_STATE_ACCESS_KEY", "TF_STATE_SECRET_KEY", "TF_STATE_REGION"):
        require(state.get(key), f"missing backend credential field: {key}")
        export_env(key, state[key])
    provider = target["provider"]
    if provider == "gcp-cloud":
        export_env("CLOUDSDK_CONFIG", str(private_dir / "gcloud-cache"), False)
    elif provider == "azure-cloud":
        export_env("AZURE_CONFIG_DIR", str(private_dir / "azure-cache"), False)
    record = read(auth["record"]) if auth.get("record") and not (bootstrap and provider == "gcp-cloud") else {}
    env_keys = {
        "aws-cloud": {}, "gcp-cloud": {}, "azure-cloud": {},
        "vultr-vps": {"VULTR_API_KEY": ("VULTR_API_KEY", "TF_VAR_vultr_api_key")},
        "akamai-cloud": {"LINODE_TOKEN": ("LINODE_TOKEN", "TF_VAR_linode_token")},
        "ucloud": {"UCLOUD_PUBLIC_KEY": ("UCLOUD_PUBLIC_KEY", "TF_VAR_ucloud_public_key"),
                   "UCLOUD_PRIVATE_KEY": ("UCLOUD_PRIVATE_KEY", "TF_VAR_ucloud_private_key"),
                   "UCLOUD_PROJECT_ID": ("UCLOUD_PROJECT_ID", "TF_VAR_ucloud_project_id"),
                   "UCLOUD_REGION": ("UCLOUD_REGION", "TF_VAR_ucloud_region")},
    }
    for field, names in env_keys[provider].items():
        require(record.get(field), f"missing provider credential field: {field}")
        for name in names:
            export_env(name, record[field])
    if provider == "ucloud":
        require(record["UCLOUD_PROJECT_ID"] == target["account"], "UCloud credential project mismatch")
        for field, variable in (("UCLOUD_SECURITY_GROUP_ID", "TF_VAR_ucloud_bootstrap_security_group_id"),
                                ("UCLOUD_KEY_PAIR_ID", "TF_VAR_ucloud_bootstrap_key_pair_id")):
            require(record.get(field), "UCloud prerequisite reference missing")
            export_env(variable, record[field])
    params = {"region": auth.get("region", ""), "role_arn": auth.get("role_arn", ""), "audience": auth.get("audience", ""),
              "tenant": auth.get("tenant", ""), "subscription": auth.get("subscription", ""), "client": auth.get("client", "")}
    if provider == "gcp-cloud":
        params.update(provider=record.get("gcp_workload_identity_provider", ""),
                      service_account=record.get("deploy_service_account", ""),
                      audience=record.get("gcp_oidc_audience", ""))
        if not bootstrap:
            require(record.get("project_id") == auth["expected_identity"], "GCP Vault project mismatch")
        export_env("TF_VAR_project_id", auth["expected_identity"], False)
        if bootstrap:
            spec = target["stages"][stage]
            import yaml
            from .contracts import contained
            declaration = yaml.safe_load(contained(os.environ["IAC_GITOPS_ROOT"], spec["manifest"]).read_text())["spec"]
            params.update(provider=auth["workload_identity_provider"], service_account=auth["service_account"], audience=declaration["audience"])
            credential = read(auth["bootstrap_record"])
            require(bool(credential.get("GCP_AUTH_JSON")) != bool(credential.get("GCP_ACCESS_TOKEN")), "exactly one bootstrap credential required")
            write_json(private_dir / "bootstrap-credential.json", credential)
            os.chmod(private_dir / "bootstrap-credential.json", 0o600)
            if credential.get("GCP_AUTH_JSON"):
                value = credential["GCP_AUTH_JSON"]
                credential_identity = value if isinstance(value, dict) else json.loads(value)
                require(credential_identity.get("project_id") == auth["expected_identity"], "bootstrap key project mismatch")
                require(credential_identity.get("client_email") != auth["service_account"] and credential_identity.get("private_key_id"), "one-time bootstrap key must differ from runtime identity")
                export_env("GCP_BOOTSTRAP_AUTH_JSON", json.dumps(credential_identity, separators=(",", ":")))
            else:
                export_env("TF_VAR_access_token", credential["GCP_ACCESS_TOKEN"])
                export_env("GOOGLE_OAUTH_ACCESS_TOKEN", credential["GCP_ACCESS_TOKEN"])
                export_env("CLOUDSDK_AUTH_ACCESS_TOKEN", credential["GCP_ACCESS_TOKEN"])
    write_json(private_dir / "auth.json", params)
    output(params)


def ucloud(action, parameters=None):
    params = {"Action": action, "PublicKey": os.environ["UCLOUD_PUBLIC_KEY"], **(parameters or {})}
    message = "".join(str(k) + str(params[k]) for k in sorted(params)) + os.environ["UCLOUD_PRIVATE_KEY"]
    params["Signature"] = hashlib.sha1(message.encode()).hexdigest()
    result = request_json("https://api.ucloud.cn", {"Content-Type": "application/x-www-form-urlencoded"}, urllib.parse.urlencode(params).encode())
    require(result.get("RetCode") == 0, "UCloud API read failed")
    return result


def verify_identity(target, runtime=True):
    provider, auth = target["provider"], target["auth"]
    wanted = auth["expected_identity"]
    if provider == "aws-cloud":
        identity = command_json(["aws", "sts", "get-caller-identity", "--output", "json"])
        require(identity["Account"] == wanted, "AWS account mismatch")
        require(not identity["Arn"].endswith(":root"), "root credentials are forbidden in the ordinary pipeline")
    elif provider == "gcp-cloud":
        identity = command_json(["gcloud", "projects", "describe", wanted, "--format=json"])
        require(identity["projectId"] == wanted, "GCP project mismatch")
        if target["environment"] == "uat" and runtime:
            forbidden = auth.get("forbidden_project")
            require(forbidden, "UAT identity needs an explicit forbidden PROD project")
            result = subprocess.run(["gcloud", "projects", "describe", forbidden, "--format=json"], capture_output=True, text=True)
            require(result.returncode != 0 and ("PERMISSION_DENIED" in result.stderr or "does not have permission" in result.stderr), "UAT/PROD isolation unproven")
    elif provider == "azure-cloud":
        identity = command_json(["az", "account", "show", "--output", "json"])
        require(identity["id"] == wanted and identity["tenantId"] == auth["tenant"], "Azure subscription/tenant mismatch")
    elif provider == "vultr-vps":
        identity = request_json("https://api.vultr.com/v2/account", {"Authorization": "Bearer " + os.environ["VULTR_API_KEY"]})
        require(identity["account"]["email"] == wanted, "Vultr account mismatch")
    elif provider == "akamai-cloud":
        identity = request_json("https://api.linode.com/v4/profile", {"Authorization": "Bearer " + os.environ["LINODE_TOKEN"]})
        require(identity["username"] == wanted, "Akamai username mismatch")
    elif provider == "ucloud":
        require(wanted == target["account"], "UCloud target/project mismatch")
        projects = ucloud("GetProjectList")["ProjectSet"]
        require(any(project["ProjectId"] == wanted for project in projects), "UCloud actual API project access mismatch")


def verify_checks(target, checks):
    require(isinstance(checks, list) and checks, "live prerequisite checks required")
    for check in checks:
        kind = check.get("kind")
        if kind == "gcp-network" and target["provider"] == "gcp-cloud":
            data = command_json(["gcloud", "compute", "networks", "describe", check["name"], "--project", target["auth"]["expected_identity"], "--format=json"])
            require(data["name"] == check["name"], "GCP network mismatch")
        elif kind == "gcp-artifact-registry" and target["provider"] == "gcp-cloud":
            data = command_json(["gcloud", "artifacts", "repositories", "describe", check["name"], "--location", check["location"], "--project", target["auth"]["expected_identity"], "--format=json"])
            require(data["name"].endswith("/repositories/" + check["name"]), "GCP registry mismatch")
        elif kind == "ucloud-firewall" and target["provider"] == "ucloud":
            wanted = os.environ["TF_VAR_ucloud_bootstrap_security_group_id"]
            data = ucloud("DescribeFirewall", {"ProjectId": target["account"], "Region": os.environ["UCLOUD_REGION"], "FWId": wanted})
            require(any(item.get("FWId") == wanted for item in data.get("DataSet", [])), "UCloud firewall not verified")
        elif kind == "ucloud-key-pair" and target["provider"] == "ucloud":
            # DescribeUHostKeyPairs has no KeyPairId request filter. Search all
            # pages and match both ID and project instead of silently using page 1.
            wanted = os.environ["TF_VAR_ucloud_bootstrap_key_pair_id"]
            offset, found = 0, False
            while True:
                data = ucloud("DescribeUHostKeyPairs", {"ProjectId": target["account"], "Region": os.environ["UCLOUD_REGION"], "Offset": offset, "Limit": 100})
                items = data["KeyPairs"]
                if any(item.get("KeyPairId") == wanted and item.get("ProjectId") == target["account"] for item in items):
                    found = True
                    break
                offset += len(items)
                if offset >= data["TotalCount"] or not items:
                    break
                require(offset <= 10000, "UCloud key pair lookup exceeded bounded pagination")
            require(found, "UCloud key pair not verified")
        elif kind == "aws-vpc" and target["provider"] == "aws-cloud":
            data = command_json(["aws", "ec2", "describe-vpcs", "--vpc-ids", check["id"], "--region", target["auth"]["region"], "--output", "json"])
            require(any(x["VpcId"] == check["id"] for x in data["Vpcs"]), "AWS VPC prerequisite missing")
        else:
            raise ContractError("prerequisite verifier not implemented")
