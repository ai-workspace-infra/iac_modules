# Historical Kubernetes UAT workdir

This directory is retained for state ownership reconciliation only. Its target is
`lifecycle.status: migration` in the GitOps IaC catalog; deployment cannot execute it.
Remove this workdir only after the read-only report verifies no remaining bindings,
or a separately reviewed state handoff retires the old ownership. This code change
performs no state removal or resource deletion.
