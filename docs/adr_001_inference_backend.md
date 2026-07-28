# ADR-001: Inference Backend Architecture

**Status:** ⏳ Pending (awaiting Community Cloud deployment evidence)  
**Date:** 2026-07-28

## Context

Chronos-2 is a 120M-parameter foundation model. This ADR decides whether to
run inference via:
- **A)** Cached local CPU inference on Streamlit Community Cloud
- **B)** A remote Chronos-2 endpoint (e.g., SageMaker, AutoGluon-Cloud)

## Decision

**Choice C — Decision pending Community Cloud evidence.**

The adapter code validates that Chronos-2 can be loaded and run on CPU
with the `predict_df` API via dependency-injected tests. However, the
following evidence is still required before confirming choice A:

- Cold-start duration on Community Cloud (platform limits to be measured)
- Warm forecast duration
- Peak memory vs. Cloud instance limits (limits to be verified during deployment)
- Stability under repeated inference
- Behaviour when the optional `HF_TOKEN` is present vs. absent
- Recovery after an inference failure

## Consequences

- If **A** is chosen, the `Chronos2Adapter` with its `st.cache_resource`-cached
  pipeline is sufficient. No API gateway or GPU endpoint is needed.
- If **B** is chosen, a new `RemoteChronos2Adapter` implementing the same
  `ForecastBackend` protocol will be added. Streamlit pages will not require
  changes.

## Linked evidence

- [Stage 0 benchmark report](stage_0_benchmark_report.md)
- Community Cloud deployment test checklist: [community_cloud_test_checklist.md](community_cloud_test_checklist.md)
