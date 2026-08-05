# Stage 0 Benchmark Report

**Generated:** 05 August 2026  
**Status:** ✅ Genuine current-head local evidence collected on commit
`7831cb4` (2026-08-05) and published as
`docs/evidence/stage0/evidence_local_stage0_bundle_20260805_171733_555681_2ce6345f.json`
(valid Gate B3 entry — supersedes the invalidated PR #18 bundle). Historical
pre-closure results are retained below for context only.

## Environment (current-head genuine run)

- Python: 3.12.10
- OS: Windows (win32)
- Model: `amazon/chronos-2`
- Configured revision: `29ec3766d36d6f73f0696f85560a422f50e8498c`
- Resolved revision: `29ec3766d36d6f73f0696f85560a422f50e8498c` (match)
- Model file SHA-256: `ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42`
- CPU: 8 logical cores
- Commit: `7831cb478bcd6beb9fcf356576f7d5096fa38c63` (worktree clean)
- HF_TOKEN present: Yes (genuine independently executed token-present run)
- Package versions:
  - torch: `2.13.0+cpu` (CUDA: None)
  - chronos-forecasting: `2.3.1`
  - pandas: `3.0.5`
  - numpy: `2.4.6`
  - streamlit: `1.60.0`

## Scenarios (current-head genuine run)

| # | Scenario | Status |
|---|----------|--------|
| 1 | Weekly series (260 obs, horizon 13) | ✅ Pass |
| 2 | Small panel (5 series, benchmark-only direct API) | ✅ Pass |
| 3 | 10 rolling forecast calls | ✅ Pass (10/10 folds) |
| 4 | Failure + successful retry (injected failure) | ✅ Pass (expected failure + same-backend retry) |

Suite passed: **True** — pipeline construction count 1, peak RSS 819.0 MB.

## Smoke measurements (current-head genuine run)

| Run | Cache state | Token | Cold total (s) | Warm total (s) | Cold RSS (MB) | Warm RSS (MB) | Revision match |
|-----|-------------|-------|----------------|----------------|---------------|---------------|----------------|
| download_cold_smoke | download_cold | absent | 59.582 | 0.228 | 713.3 | 715.0 | ✅ |
| process_cold_smoke | process_cold_cached_weights | absent | 24.213 | 0.379 | 520.7 | 543.4 | ✅ |
| token_present_smoke | process_cold_cached_weights | **present** | 21.010 | 0.209 | 826.0 | 827.1 | ✅ |

All three smoke runs resolved the pinned revision `29ec3766...` exactly.
`token_present_smoke` is a genuinely independent run (unique run ID and
timestamps — verified by `build_local_stage0_bundle.py`'s duplicate-evidence
checks).

## Benchmark results (current-head genuine run)

### Scenario 1: Weekly cold/warm

| Sample | Duration (s) | Success |
|--------|-------------|---------|
| Cold forecast | 3.861 | ✅ |
| Warm forecast | 0.250 | ✅ |

Pipeline construction count: 1 (reused for warm, panel, and rolling)

### Scenario 2: Panel (5 series)

| Sample | Duration (s) | Success |
|--------|-------------|---------|
| Panel forecast | 0.981 | ✅ |

### Scenario 3: 10 rolling calls

| Sample | Duration (s) | Success |
|--------|-------------|---------|
| Fold 0 | 0.207 | ✅ |
| Fold 1 | 0.228 | ✅ |
| Fold 2 | 0.217 | ✅ |
| Fold 3 | 0.248 | ✅ |
| Fold 4 | 0.210 | ✅ |
| Fold 5 | 0.258 | ✅ |
| Fold 6 | 0.233 | ✅ |
| Fold 7 | 0.225 | ✅ |
| Fold 8 | 0.268 | ✅ |
| Fold 9 | 0.308 | ✅ |
| Total (10 folds) | 2.402 | ✅ |

### Scenario 4: Failure + retry

| Sample | Success | Notes |
|--------|---------|-------|
| Injection failure test | ❌ (expected) | AdapterError: safe failure on first call |
| Retry success | ✅ | Same adapter recovers on retry |

## Key Measurements

| Metric | download-cold cold | process-cold cold |
|--------|-------------------|-------------------|
| Total time | 59.582s | 24.213s |
| Warm inference (13-step) | 0.228s | 0.379s |
| Peak RSS | 713.3 MB | 520.7 MB |
| Pipeline reuse | ✅ | ✅ Verified (real model) |

## Community Cloud Results

*Pending — deploy technical spike, collect evidence, then decide ADR-001.
This is the correct sequence: deployment produces the evidence the ADR needs.
The genuine local bundle now satisfies Gate B3, so the Cloud trial (Gate C)
is the remaining Stage 0 evidence gate.*

---

## Historical context (pre-integrity-closure, July 2026 — informational only)

Prior local evidence existed but was collected before the
evidence-integrity closure; the 29 July bundle was invalidated (fabricated
token-present record) and is not valid release evidence. The current-head
genuine run above supersedes it.
