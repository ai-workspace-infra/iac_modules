# Skill: release-branch-policy

## Purpose

Standardize release branch policy across Cloud-Neutral Toolkit repos:

- `main` is the **preview** branch (fast iteration, integrates frequently).
- `release/*` branches are **production release lines** and must be protected.
- Updates to `release/*` happen via **local cherry-pick** by release managers (process gate).

This skill includes:
- A policy doc (this file)
- A ruleset JSON template (GitHub Rulesets API)
- A `gh` script to apply the ruleset to one or many repos
- A sync script to copy this skill into all local sub-repos
- A script to generate a cross-repo release manifest (for tag association)

Non-goals:
- This skill does NOT create/push `release/v0.1` or tags automatically.

## Policy

### Branch Roles

- `main`: preview
  - Accepts PRs and merges normally.
  - May be ahead of production at any time.
- `release/*`: production
  - No force-push.
  - Require linear history.
  - Prefer "cherry-pick into release branch" as the only change mechanism (process).
  - Restrict who can update release branches to release managers (enforced via GitHub Rulesets/Branch protection UI).

### “Cherry-Pick Only” Clarification

GitHub branch rules cannot reliably guarantee "only cherry-pick" as a technical constraint.
We treat it as a **process rule**:

1. A change lands in `main`.
2. Release manager cherry-picks specific commits onto `release/<version>`.
3. Release manager pushes the updated release branch.

### “No PR / No Push” Clarification

If you literally forbid both:
- PR merges to `release/*`, and
- any push to `release/*`

then the branch becomes non-updatable.

What we implement is:
- No force-push, no deletion, linear history (enforceable).
- Only release managers can update `release/*` (enforceable via "restrict updates" / bypass actors).
- "Cherry-pick only" (process rule).

### Tags

For milestone releases like `v0.1`:
- Use an annotated tag named `v0.1` (per-repo).
- Prefer tags on `release/<version>` tip.

If you need SemVer tags, follow governance: `<repo>-vX.Y.Z`.

### Cross-Repo Tag Association

Git tags are per-repo; GitHub does not provide a first-class "one tag links all repos" concept.

We represent "release v0.1 across repos" by committing a **release manifest** file in the control repo, generated from local git state:
- repo name
- release branch tip SHA
- tag tip SHA

Use: `skills/release-branch-policy/scripts/generate_release_manifest.sh v0.1`

## Ruleset Requirements (release/*)

Enforce at minimum:
- block deletion
- block force-push (non-fast-forward)
- require linear history

Optional (recommended if you have stable CI):
- require status checks
- require signed commits

## Tools

### 1) Apply Ruleset (GitHub Rulesets)

Script: `skills/release-branch-policy/scripts/apply_ruleset.sh`

- Applies (create/update) a repo ruleset targeting `refs/heads/release/*`
- Uses `gh api` and a JSON payload
- Does not modify branches/tags

### 2) Sync Skill Into All Local Sub-Repos

Script: `skills/release-branch-policy/scripts/sync_skill_to_subrepos.sh`

- Copies this skill folder into each local repo under `/Users/shenlan/workspaces/cloud-neutral-toolkit/*`
- Skips repos without `.git`
- Keeps existing files unless overwritten explicitly

### 3) Generate Release Manifest (Cross-Repo Association)

Script: `skills/release-branch-policy/scripts/generate_release_manifest.sh`

- Generates `releases/<version>.yaml` in the current working directory (default)
- Does not push or create refs

## Operator Checklist

- Confirm `main` is treated as preview across repos (docs + CI naming).
- Apply ruleset to every repo that has production releases.
- Document "cherry-pick only" in release runbooks.
- Verify bypass actors (release managers) in GitHub UI if needed.
