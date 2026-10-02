# Legacy pipeline definitions (parked)

These files were stored under `.github/actions/` but are workflow-shaped
(`on:` / `jobs:`), not composite actions, so GitHub never ran them. They are kept
here for reference only; moving them back under `.github/workflows/` would
re-enable them.

`scripts/evaluate-workflow-status.js` is the helper they `require()`; the path
inside the archived files still reads `./.github/scripts/evaluate-workflow-status`
and must be adjusted if one is revived.

The pipelines that actually run live in `platform-ops-toolkit`; the Terraform-phase
steps they call are in [`scripts/pipeline/`](../../../scripts/pipeline/).
