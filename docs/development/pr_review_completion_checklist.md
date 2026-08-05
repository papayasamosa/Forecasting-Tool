# PR Review Completion Checklist

A pull request is mergeable only when **every** review finding satisfies the
resolution evidence contract below. A discussion thread whose GitHub state
says "resolved" is **not** proof of resolution — the fixing commit and
regression test must be verified in the code.

## Per-finding resolution record

Every review finding must record:

| Field | Required | Meaning |
|---|---|---|
| Finding URL | yes | Link to the review comment / discussion thread |
| Severity | yes | P0, P1, P2, or other |
| Fixing commit | yes | Exact commit SHA that remediates the finding |
| Regression test | yes | Exact test(s) that would fail without the fix |
| Reviewer re-check | yes | Reviewer confirmation, or documented evidence of remediation on the latest head SHA |
| Resolution time | yes | Timestamp when the fix was verified |

A thread marked resolved without those fields is **not** a satisfied merge
gate.

## Worked example — the PR #27 colon-delimited secret finding

- **Finding URL:** `https://github.com/papayasamosa/Forecasting-Tool/pull/27#discussion_r...`
- **Severity:** P1
- **Fixing commit:** the WP1 commit in PR `stage0-pr27-review-and-autonomous-gate-closure`
- **Regression tests:** `tests/test_redaction.py::TestColonDelimitedSecrets`,
  `tests/test_redaction_contract.py::TestColonDelimitedContractAcrossReceiptPaths`
- **Delimiter contract:** detection and sanitisation share one assignment
  grammar (`=` or `:`, optional surrounding whitespace); a safe marker
  exempts only the matched value, never a surrounding window.
- **Reviewer re-check:** reviewer re-verified the colon forms on the latest
  head SHA.
- **Resolution time:** recorded when CI and review completed on the latest
  head.

## Rules

- Review findings submitted after CI becomes green restart the gate loop
  (fresh head SHA, fresh CI, fresh review).
- P0 and P1 findings are blockers even when CI is green.
- Never resolve a thread without a verified remedy.
- Never fabricate a review or a resolution.
- The evidence-and-documentation consistency check is part of the review
  gate: claims in README, ADRs, and evidence must match the code.
