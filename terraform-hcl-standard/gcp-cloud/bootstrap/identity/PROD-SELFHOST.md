# PROD Selfhost bootstrap versus daily OIDC

The existing bootstrap identity stack declares the runtime project roles,
including `roles/compute.securityAdmin`. Its platform API set must enable
`orgpolicy.googleapis.com` before resource stacks use the Organization Policy
API. Bootstrap API/role declarations do not prove those contracts are live.

PROD resource apply 37461248828 authenticated through the existing GitHub
`prod` environment/WIF identity. It created the network, subnet and independent
disk, then failed because Organization Policy API was disabled,
`compute.firewalls.create` was denied and the VM external IP allowlist did not
permit the new instance. Preserve those created resources in the existing
Web SaaS state; do not re-create or replace them in another state.

Repair the existing bootstrap contract once with a privileged, short-lived
bootstrap principal. Review additive IAM/API differences and the exact
GitOps external IP allowlist. Organization policy administration is a separate
privileged boundary; do not grant the runtime deployer organization-wide
administrator privileges. Daily resource runs remain GitHub OIDC/Vault/WIF and
must not use a personal GCP login or a stored Service Account key.

The renderer now makes service VM creation depend on the declared external IP
policy when that policy is managed by the stack. A failed policy cannot race
VM creation in the same apply. VM/disk identities and state addresses are
unchanged. A fresh actual plan must still show no delete/replace before retry.

This change does not apply live IAM/API/policy resources or certify VM,
persistent mount, database initialization, business copying, or DB cutover.
