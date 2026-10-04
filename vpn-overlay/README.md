# XConnect Zero Trust infrastructure modules

This directory contains reusable infrastructure modules only. It does not
contain host configuration, runtime scripts, credentials, product plans, or
environment-specific topology.

## Modules

| Module | Purpose | Creates |
| --- | --- | --- |
| `xconnect-lab` | Disposable UAT data-plane validation | Two isolated ARM64 AWS Spot instances and scoped security groups; it reuses the existing UAT network. |

`xconnect-lab` intentionally has no Terraform provisioners. Its cloud-init
template is limited to instance bootstrap metadata and a scoped SSH public
key; Xray/WireGuard/Gateway/One installation is an OS runtime responsibility
of the `playbooks` repository.

The reviewed, non-sensitive UAT declaration belongs in
`gitops/vpn-overlay/uat/xconnect-lab.json`. Secrets and per-device private
keys are never committed: runtime consumers obtain them from the environment's
Vault path.
