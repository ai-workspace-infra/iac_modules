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

## Bounded administrator repair entry

The Toolkit controller lives under `scripts/cloud/bootstrap/gcp/`; its fixed
IaC owner is `terraform-hcl-standard/gcp-cloud/scripts/bootstrap_prod_selfhost.sh`.
It supports two separately reviewed stages:

| Stage | Allowed write | Existing state |
| --- | --- | --- |
| `identity` | Project `compute.securityAdmin` and `orgpolicy.policyViewer` grants to the existing PROD deployer; enable `orgpolicy.googleapis.com` | `platform-ops-toolkit/prod/xworktech/gcp-oidc-bootstrap/terraform.tfstate` |
| `external-ip` | Adopt the existing project policy, preserve `open-platform-prod`, and add only `web-saas-prod` | `terraform/prod/svc.plus/gcp-cloud/xworktech/web-saas/terraform.tfstate` |

The caller pins clean IaC and GitOps checkouts by full commit SHA. The owner
requires the existing WIF/Service Account state for the first stage and the
existing network/subnet/independent data disk state for the second. It refuses
an empty or alternate state. The unchanged protected state fingerprints are
checked again after apply. Terraform targeting is limited to this audited
repair; daily resource deployment still uses the complete manifest and plan.

For each stage run `plan`, review its sanitized resource contracts and
`approved_plan_sha256`, then run `apply` with that digest. Apply generates a
fresh plan and refuses a changed source, state serial, target action or target
value. It applies that saved plan, then checks that another plan is all no-op.
An existing policy outside state is adopted through a reviewed import block
into the same namespace state; it is not recreated in another stack. Existing
undeclared allowances, broad or conditional policies require separate review.
No VM/network/disk changes are permitted by either bootstrap stage.

Live inspection on 2026-10-06 found the existing V2 policy created on 2026-09-29,
with parent `projects/986070475391` and a sole allowance for
`projects/open-platform-prod/zones/asia-east1-a/instances/open-platform-prod`.
The earlier `projects/open-platform-prod` parent alias forced delete/create
after import, and removing that preexisting allowance was also prohibited.
GitOps now explicitly selects `external_ip_policy_parent_identity: project_number`
for this namespace and preserves that one old allowance alongside the new one.
Other namespaces keep the existing project-ID default. Both parent and exact
allowances remain managed; no ignore rule for parent or broad project allowance
is introduced. Legacy permission retirement is a separate reviewed change.

`--diagnostic-plan` is a read-only owner troubleshooting option. It emits only
resource addresses/actions/replacement paths and policy shape, then still runs
the guards. It cannot apply or issue a convergence/cutover receipt. Fixed guard
reasons are reported; arbitrary provider/parser diagnostics remain private.

Credentials are an approved short-lived `GCP_BOOTSTRAP_ACCESS_TOKEN` plus the
existing Vault `TF_STATE_*` environment contract. The owner uses
`GOOGLE_OAUTH_ACCESS_TOKEN` and AWS backend environment credentials, never
token tfvars, credential files, CLI arguments or raw plan artifacts. Temporary
workspaces are mode 0700 and are removed on success/failure. Arbitrary provider
diagnostics are withheld because they can contain secrets. There is no
automatic fallback to a personal login or runtime identity. The explicit
`--bootstrap-account EMAIL` option may acquire a short-lived token from that
already authorized local account for this one-time repair. Login renewal is
performed by the user, never automatically by the owner. This option is not
available in daily deployment workflows.

## Shell integration

Toolkit and the provider repair owner now use Bash with jq guards, replacing
both custom Python bootstrap programs. Toolkit prepares clean, pinned source
checkouts automatically; manual `/path/to/pinned-*` directories are unnecessary.
The existing Vault auth/identity/state scripts retain their separate contracts;
the shared-policy seeder is not used to write the PROD policy outside Terraform.

`identity` needs Bash, Git, jq, Ruby (safe YAML decoding), shasum and Terraform
1.10+. `external-ip` also needs curl and the existing shared IaC renderer's
Python/PyYAML 6.0.2/Jinja2 3.1.6 runtime. `IAC_RENDER_PYTHON` may select an
already prepared interpreter. The renderer is required by the repository's
Terraform YAML rendering standard; it is not a second bootstrap controller.
No inline Python, Python wrapper, alternate HCL renderer, or new state owner
is introduced. Raw diagnostics and state remain private and are removed.

The administrator needs project IAM/API enablement permissions for `identity`
and existing organization policy administration for `external-ip`. Do not
grant `orgpolicy.policyAdmin` to the daily deployer. Google's role reference
lists `policyViewer` as grantable at project scope, while `policyAdmin` has
organization as its lowest grantable scope:
[Organization Policy roles](https://docs.cloud.google.com/iam/docs/roles-permissions/orgpolicy).
The provider documents the environment-only short token option:
[Google provider authentication](https://registry.terraform.io/providers/hashicorp/google/latest/docs/guides/provider_reference).

Failure may leave only the allowed grants/API/policy partially converged;
re-plan the same stage/state rather than reverse/delete IAM or recreate disks.
After both convergence receipts, resume the daily OIDC resource **plan** and
review zero delete/replace before apply. Bootstrap receipts explicitly do not
approve database cutover.
