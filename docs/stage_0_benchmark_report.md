# Stage 0 Benchmark Report

**Generated:** 29 July 2026  
**Status:** ✅ Local evidence complete (D: drive — no token)

## Environment

- Python: 3.12.10
- OS: Windows (win32)
- Model: `amazon/chronos-2`
- Configured revision: `29ec3766d36d6f73f0696f85560a422f50e8498c`
- Resolved revision: `29ec3766d36d6f73f0696f85560a422f50e8498c` (match)
- Model file SHA-256: `ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42`
- CPU: 8 logical cores
- HF_TOKEN present: No (token-present test: ✅ model resolved correctly)
- Package versions:
  - torch: `2.13.0+cpu` (CUDA: None)
  - chronos-forecasting: `2.3.1`
  - pandas: `3.0.5`
  - numpy: `2.4.6`
  - streamlit: `1.60.0`

## Scenarios

| # | Scenario | Status |
|---|----------|--------|
| 1 | Weekly series (260 obs, horizon 13) | ✅ Pass |
| 2 | Small panel (5 series, benchmark-only direct API) | ✅ Pass |
| 3 | 10 rolling forecast calls | ✅ Pass (10/10 folds) |
| 4 | Failure + successful retry (injected failure) | ✅ Pass (expected failure + same-backend retry) |

## Local Results

### Scenario 1: Weekly cold/warm

| Sample | Duration (s) | Load (s) | Inference (s) | Baseline RSS (MB) | Peak RSS (MB) | Success |
|--------|-------------|---------|--------------|------------------|--------------|---------|
| Cold forecast | 3.352 | 1.373 | 1.974 | 350 | 824 | ✅ |
| Warm forecast | 0.268 | 0.000 | 0.265 | 824 | 825 | ✅ |

Pipeline construction count: 1 (reused for warm, panel, and rolling)

### Scenario 2: Panel (5 series)

| Sample | Duration (s) | Load (s) | Inference (s) | Baseline RSS (MB) | Peak RSS (MB) | Success |
|--------|-------------|---------|--------------|------------------|--------------|---------|
| Panel forecast | 0.516 | 0.000 | 0.516 | 824 | 825 | ✅ |

### Scenario 3: 10 rolling calls

| Sample | Duration (s) | Success |
|--------|-------------|---------|
| Fold 0 | 0.478 | ✅ |
| Fold 1 | 0.438 | ✅ |
| Fold 2 | 0.417 | ✅ |
| Fold 3 | 0.421 | ✅ |
| Fold 4 | 0.419 | ✅ |
| Fold 5 | 0.407 | ✅ |
| Fold 6 | 0.401 | ✅ |
| Fold 7 | 0.405 | ✅ |
| Fold 8 | 0.397 | ✅ |
| Fold 9 | 0.404 | ✅ |
| Total (10 folds) | 4.188 | ✅ |

### Scenario 4: Failure + retry

| Sample | Success | Notes |
|--------|---------|-------|
| Injection failure test | ❌ (expected) | AdapterError: safe failure on first call |
| Retry success | ✅ | Same adapter recovers on retry |

## Key Measurements

| Metric | Cold | Warm |
|--------|------|------|
| Model load time | 1.373s | N/A |
| Inference time (13-step) | 1.974s | 0.265s |
| Total time | 3.352s | 0.268s |
| Baseline RSS | 350 MB | 824 MB |
| Peak RSS (approximate) | 824 MB | 825 MB |
| Pipeline reuse | N/A | ✅ Verified (real model) |

## Community Cloud Results

*Pending — deploy after ADR-001 decision.*
