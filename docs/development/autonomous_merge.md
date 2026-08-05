# Autonomous Merge State Machine

This document defines the exact gate sequence an autonomous agent must
follow before merging any pull request into `main` on this repository.

## Repository governance (verified 2026-08-05)

| Setting | Value | Verification |
|---|---|---|
| Default branch | `main` | GitHub API |
| `allow_auto_merge` | `false` | GitHub API (requires repository-administration permission to enable) |
| `allow_update_branch` | `false` | GitHub API (requires repository-administration permission to enable) |
| Ruleset | `main-protection` (id `20114421`) targets `refs/heads/main` | GitHub API |
| Ruleset enforcement | **disabled** — rules are configured (pull request review count 1, required status check `test (3.12)`, conversation resolution, non-fast-forward) but the ruleset is not currently active | GitHub API |
| Bypass actors | none; `current_user_can_bypass = never` | GitHub API |

The autonomous agent's token has `push`/`maintain` but **not** the
repository-administration scope, so it cannot enable auto-merge, enable
update-branch, or activate the ruleset. Those changes require a human with
admin rights. Until then the agent uses the **direct merge fallback** below
and never claims auto-merge is active.

## States

```
PREPARING
IMPLEMENTING
LOCAL_VALIDATION
PR_OPEN
CI_RUNNING
CI_FAILED
REVIEW_PENDING
REVIEW_CHANGES_REQUIRED
MERGE_READY
MERGING
POST_MERGE_CI
STAGE_COMPLETE
BLOCKED
```

## Mandatory gate order (per PR)

1. Fetch the latest `main` and verify the expected base commit.
2. Create/update the named branch and implement the scoped work.
3. Run local validation (D-drive venv, offline, `--basetemp` on D:).
4. Commit with a descriptive message and push automatically.
5. Open the pull request and record the exact head SHA.
6. Monitor required CI checks (`test (3.12)`).
7. On failure: inspect the full log, identify the first causal error,
   classify it (product / test / environment / workflow / flaky / outage),
   reproduce locally where feasible, fix the root cause, add a regression
   test, rerun local checks, commit and push the remedy, repeat.
8. **Review gate:** obtain or trigger review on the latest head SHA. Inspect
   every comment and discussion. Treat P0 and P1 findings as blockers even
   when CI is green.
9. **Discussion gate:** every thread must either be genuinely resolved (see
   the completion checklist) or have no open status. A thread marked
   resolved without a fixing commit and regression test is not satisfied.
10. **Freshness gate:** the branch must be current with `main`; rerun CI
    after every material change or update.
11. **Merge gate (all must hold):**
    - all required CI checks green on the exact head SHA
    - completed review on the latest head commit
    - zero unresolved discussions
    - zero unremediated P0/P1 findings
    - every finding mapped to a fixing commit and regression test
    - branch up to date with `main`
    - no unexpected changes after the final review
    - evidence and documentation claims consistent with the code
    - no secret exposure
    - no bypass or administrator override
12. Merge automatically only when every gate passes.

## Preferred merge implementation

1. Verify repository auto-merge and branch ruleset settings.
2. Enable repository auto-merge only when authorised (admin scope present
   and the repository settings API confirms the change).
3. Preserve the repository's established merge-commit strategy unless
   governance requires another method.
4. Enable auto-merge on the PR only after review and discussion gates are
   satisfied; let GitHub merge when required checks turn green.

## Direct merge fallback (used when auto-merge cannot be enabled)

1. Poll the PR checks while the execution session is active.
2. Verify all merge gates directly (CI, review, discussions, P0/P1 mapping,
   freshness, no unexpected changes, no secrets).
3. Call the GitHub merge operation immediately after all gates pass.
4. Record the exact merge commit from the API response.

## Never

- merge only because CI is green
- merge before review completes
- merge with an unresolved or unremediated P0/P1 finding
- use an administrator bypass
- disable a required check
- weaken a coverage or validation gate to force green status
- force-push `main`
- push directly to `main`
- fabricate a review
- resolve a thread without a verified remedy
- merge an outdated head SHA
- proceed when the exact merge commit has no successful main-branch CI run

## Post-merge verification

- Record the exact merge commit.
- Verify the push-to-main workflow run for that exact merge commit.
- If post-merge CI fails on the merge commit: do not commence the next
  stage. Revert promptly when release integrity, security, or evidence
  validity is at risk; otherwise open a narrow hotfix PR through the same
  gated loop.
- Only mark the stage complete after the exact merge commit is green.

## Required completion report fields

Every stage reports: stage, state, branch, base commit, head commit, files
changed, scope completed, local commands, tests, skipped tests, warnings,
aggregate coverage, critical-module coverage, readiness result, D-drive
runtime facts, D-drive compliance, MCP/Graphify tools actually used, PR
number, PR head SHA, CI workflow run, CI failures encountered, remedies
pushed, review state, review findings, finding-to-commit mapping,
finding-to-test mapping, discussion state, repository auto-merge setting,
applicable branch ruleset, merge method, merge commit, post-merge main
workflow run, post-merge conclusion, evidence status, next stage commenced,
blocking reason.

Never report a stage as complete when any required field is unknown,
failed, fabricated, or unverified.
