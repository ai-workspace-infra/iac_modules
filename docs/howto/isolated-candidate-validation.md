# Isolated candidate validation cleanup

Before replacing a candidate, prepare its trusted new-host identity route.
The Akamai bootstrap emits only the public Ed25519 SHA256 fingerprint in short,
framed console lines. `scripts/pipeline/akamai-hostkey-read.py` validates the
account/instance/region/address, reads the provider's TLS-verified Weblish endpoint
without keyboard input, requires one complete 256-bit fingerprint, and compares
it with the network key before emitting a protected `known_hosts` file and receipt.
It consumes `LINODE_TOKEN` only from the runtime environment, passes the ephemeral
console session through stdin, and never accepts key/fingerprint prefixes.
Use a fresh evidence directory and capture boot output before host deployment;
missing or conflicting frames block SSH. Existing instances are not restarted or
reconfigured by this reader. A verified fingerprint does not prove host/service
readiness or business acceptance.

Owner: IaC Modules. Caller: Toolkit `iac-orchestrator.yml`, resources stage only.
GitOps declares the serving source, candidate namespace and one compute owner.
This mode does not change the shared Selfhost orchestrator's production destroy
prohibition. It initially supports Akamai candidates only.

The candidate resource declaration keeps `global.prevent_destroy: true`.
A reviewed `IaCPipelineTargets` entry opts into `validation.mode: cleanroom`,
references the serving source target manifest/ID, and names exactly one compute
module in `validation.destroy_owners`. The resource stage authorizes destroy,
explicitly protects retained resources and owns a canonical, separate state key.

Before a mutating run, the operator verifies an externally retained, restorable
candidate data backup and records its receipt/digest in the controlled change
record. Instance-local backups are insufficient. No backup or source data is
deleted by this operation. Candidate business acceptance and final traffic/write
cutover remain separate operations.

The owner fails closed unless:

- Serving source and candidate namespaces, manifests and state keys differ.
- The candidate has one host, an explicit candidate group, disabled public
  cutover/background writers and no independent storage declaration.
- Both live states exist, have distinct lineages and contain no common managed
  cloud resource identity, including provider aliases.
- Candidate state belongs only to its declared owners and selects one instance.
- The refreshed saved plan deletes precisely the selected instance, with the
  expected live label and region. Disks, firewalls, DNS, identities and unrelated
  objects cannot be deleted or replaced.
- Instance-bound provider backups are disabled; otherwise cleanup stops to avoid
  implicitly deleting those recovery objects with their instance.

Only the private cleanup render temporarily removes instance deletion protection
using the existing explicit renderer authorization. The GitOps declaration stays
protected; the next normal apply renders protection automatically. Terraform
plans only the selected compute module, applies that exact saved plan under the
backend lock, then verifies all retained resource identities and the serving
source state are unchanged. A targeted plan which includes a protected dependent
is rejected; there is no provider-delete fallback.

Raw source/candidate state and Terraform logs remain private runner data and are
removed by the existing credential cleanup. The remote backend object and its
history remain in place; there is no `state rm`, backend migration or source
apply. Sanitized receipts carry state digests, isolation, retained-resource and
source-unchanged verification. Missing source-state read access blocks the run;
it does not authorize wider credentials.

After cleanup, `action=apply` with the same reviewed target recreates the
candidate and emits fresh CMDB. Only that CMDB may drive Playbooks. Run the
fixed deployment once, then at least three identical deployment replays;
preview/apply the approved migration, then at least three fresh no-op previews
and replays. Record immutable refs, independent run IDs, Shanghai timestamps,
configuration/image/container/restart and database/schema/data digests. Local
contracts or Terraform convergence alone are not runtime idempotence evidence.
