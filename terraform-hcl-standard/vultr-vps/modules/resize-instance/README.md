# resize-instance

Creates a Vultr replacement instance for a resize operation. The module is
intentionally isolated from the primary environment state so a failed backup,
restore, health check, or DNS cutover cannot destroy or rewrite the source
instance.

The caller must provide either `snapshot_id` or `os_id`. Backup creation,
service restore, health checks, DNS/Reserved IP cutover, observation, and
source-instance cleanup are orchestration concerns owned by the delivery
workflow.

The replacement resource has `prevent_destroy = true`; cleanup must be an
explicit, separately approved operation after the observation window.
