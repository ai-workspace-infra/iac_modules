"""Provider-neutral Terraform state identity; topology belongs to GitOps."""
import re

_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@+-]{0,126}")

def component(name, value):
    if not isinstance(value, str) or not _COMPONENT.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"invalid state identity {name}")
    return value

def validate_namespace(namespace, **_):
    component("namespace", namespace)
    if namespace in {"selfhost", "all", "default", "shared"}:
        raise ValueError("shared Terraform namespace is forbidden")
    return namespace

def canonical_state_key(*, environment, project, provider, account, namespace):
    values = {"environment": environment, "project": project, "provider": provider, "account": account}
    for name, value in values.items():
        component(name, value)
    if account in {"primary", "default", "main"}:
        raise ValueError("concrete provider account required")
    validate_namespace(namespace)
    return f"terraform/{environment}/{project}/{provider}/{account}/{namespace}/terraform.tfstate"
