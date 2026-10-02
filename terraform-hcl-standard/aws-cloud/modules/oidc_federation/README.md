# AWS OIDC federation module

This module creates one AWS IAM OIDC provider and one role with an exact
`sub` and `aud` trust condition. It is intended for a ZITADEL workload JWT or
another verified OIDC issuer. It does not attach permissions: the caller must
attach a narrowly scoped managed or inline policy in the account-specific
configuration.

The module deliberately does not accept a wildcard subject. Separate roles are
required for separate environments, repositories, or workloads. The issuer
URL, client ID, and CA thumbprint must be recorded in the corresponding
non-secret GitOps declaration and Vault bootstrap record.
