# GitOps IaC target catalog

GitOps owns `iac/catalog.yaml`. Its `target_manifests` references ordinary
`IaCPipelineTargets` documents; deployment and read-only state inspection call
`unified.contracts.load_targets` at the same resolved GitOps SHA. There is no
provider-local list of supported resource domains.

Each catalog target declares environment, project, provider, concrete account,
namespace, resource manifest and lifecycle. `workspace` is a compatibility alias
and must equal namespace. One provider-neutral function in
`terraform-hcl-standard/scripts/iac_identity.py` computes the canonical state key.
The retained explicit key is validated against it; existing states are never
renamed or imported by selecting the catalog.

Deployment selects active targets and accepts explicit provider/account/namespace
constraints. Migration and retired targets are inspection-only, even when selected
through a direct target file. Persistent targets cannot be destroyed. Legacy target
files without explicit namespace/lifecycle remain readable for offline checks,
but cannot execute plan/apply/destroy with this owner version.

Historical shared-state sources are separate catalog entries with read-only
lifecycle, exact state identity and immutable provenance. The legacy migration
report accepts one historical shared source per selected account/scope; multiple
shared origins fail closed and require separate scope catalogs. Any number of
target namespaces may be inspected. Historical target manifests may omit SSH and
business configuration because the inspection path only reads resource identity.

`unified_cli.py catalog-check` validates all referenced target files without
credentials. Prepare/revalidate records the catalog and referenced file digests,
selected targets, source SHAs and canonical state keys. The query path verifies the
actual provider username before inspecting state, retains every managed binding,
and distinguishes ID/label disagreement from an empty state. It never suggests
create/import for a migration target and never authorizes state removal.

Consumer rollout order is declaration PR, owner PR, then Toolkit consumer pin.
Use immutable reviewed commits, run offline contracts, then run read-only UAT
preflight. Historical workdirs remain until the state is verified empty or a
separately reviewed state handoff is complete. This implementation does not apply
Terraform, move/remove state, or mutate provider resources.
