# Chronos-2 Forecasting Tool

A Streamlit application for time-series forecasting using **Amazon Chronos-2**, a 120M-parameter foundation model for zero-shot forecasting.

## Status

| Component | Status |
|-----------|--------|
| Schemas and configuration | ✅ Implemented, tested |
| `ForecastBackend` protocol | ✅ Implemented |
| `Chronos2Adapter` class | ✅ Implemented, tested with fake pipeline |
| Schema invariant validation | ✅ Implemented, tested |
| Unit tests (no model download) | ✅ Implemented |
| Local setup (D: drive) | ✅ Documented, enforced |
| CI (GitHub Actions) | ✅ Fail-closed: `--cov-precision=2` + independent `coverage report` gate + workflow-contract regression test, threshold 82% (actual ~90%), `workflow_dispatch` recovery trigger, correctness lint (`E9,F63,F7,F82,F402,F541,F811,F841,W605`) enforced across `src/` and `scripts/` |
| `st.cache_resource` process-level caching | ✅ Implemented |
| Pipeline reuse (unit-tested with fake pipeline) | ✅ Implemented |
| Context capping before record materialisation | ✅ Implemented |
| Truncation warnings displayed in UI | ✅ Implemented |
| Warm reuse enforced in benchmark gate | ✅ Implemented |
| Explicit `cross_learning=False` in standard calls | ✅ Implemented |
| Failure telemetry recorded | ✅ Implemented |
| Summary calculations exclude aggregate | ✅ Implemented |
| Smoke evidence written on all failure paths | ✅ Implemented |
| Reusable telemetry module (`src/telemetry.py`) | ✅ Implemented |
| Immutable model revision pinned | ✅ `29ec3766d36d6f73f0696f85560a422f50e8498c` |
| Evidence schemas (v2) with typed models | ✅ Implemented |
| Process-wide inference coordinator (`src/coordinator.py`) | ✅ Implemented with semaphore, tests, bounded history |
| Production page routes forecasts through the coordinator | ✅ Implemented (`pages/1_Forecast.py`) |
| Coordinator returns execution record (no full-history scan) | ✅ Implemented |
| Typed repeated-run records | ✅ Implemented |
| Typed concurrency evidence | ✅ Implemented |
| Token-absent and token-present path results | ✅ Implemented, both required for Cloud |
| Cloud acceptance-test evidence | ✅ Schema complete, all tests required |
| Cloud evidence bound to deployed commit | ✅ Validated |
| Cloud resource/memory evidence | ✅ Required |
| Typed Cloud runtime diagnostics (`src/cloud_diagnostics.py`) | ✅ Implemented — allowlisted snapshot, exact deployed-commit resolution (40-hex fail-closed), request-scoped memory sampling, bounded request telemetry, measured dependency diagnostics, token state boolean only |
| Cloud Diagnostics page (`pages/3_Cloud_Diagnostics.py`) | ✅ Implemented — read-only safe metadata, deterministic JSON download, canonical digest, collection-session begin/finalise (no secret input) |
| Cloud collection-session + receipt binding (WP11) | ✅ Implemented — session binds deployed commit, URL, diagnostics digest, request/token/repeated/concurrency/timeout IDs; receipt binds the session's canonical digest |
| Cloud instrumentation readiness checks (WP13) | ✅ Implemented in `scripts/verify_stage0_evidence_readiness.py` |
| Evidence publisher (sanitise, copy, manifest) | ✅ Implemented |
| Bundle builder with recursive typed validation | ✅ Implemented, shared validator |
| Manifest deep verifier (internal JSON validation) | ✅ Implemented, uses Path.is_relative_to() |
| Cache preflight evidence required | ✅ Built from pre/post cache inspections via `build_cache_preflight()` |
| Cache inspection returns `inspection_succeeded` and `error_code` | ✅ Added — expected absence not a failure |
| Suite-level resolved revision and peak RSS | ✅ Mandatory, measured (not defaulted) |
| HF cache discovery (huggingface_hub constant) | ✅ Implemented |
| Cloud evidence validation (strict states, concurrency gate) | ✅ Pairwise interval intersection |
| Snapshot/weight file count metadata | ✅ Implemented, validated |
| Producer/schema alignment (allowlist + warning) | ✅ Implemented |
| Git traceability (trustworthy repo-root detection) | ✅ Implemented |
| Blank/missing timestamp rejection | ✅ Implemented |
| MCP static CI verification | ✅ Implemented |
| Self-contained CPU Torch dependency declaration | ✅ Implemented |
| Windows machine CPU model detection | ✅ Implemented |
| Evidence manifest hash verification (CI) | ✅ Implemented |
| Functional evidence CLI tests (subprocess) | ✅ Implemented |
| Execution receipts (WP3) | ✅ First-class evidence type with `evidence_schema_version`, `evidence_type`, registered in type map, deserializable, recursively validated, with `write_execution_receipt()` helper |
| Receipts bound to components (transport hash) | ✅ Typed, mandatory for passing bundles — validates hash, commit, revision, model, execution ID uniqueness |
| Receipts bound to components (canonical content digest) | ✅ `canonical_evidence_sha256()` — deterministic JSON serialisation; `LocalStage0Bundle._validate_receipts()` recomputes canonical digest from embedded component and compares with receipt's `canonical_content_sha256` |
| Evidence finalisation order | ✅ Sanitisation before receipt binding; publication cannot mutate semantic content after receipt finalisation |
| Evidence origin isolation | ✅ `evidence_origin` field (`real_measurement` / `synthetic_fixture`); publisher rejects `synthetic_fixture` |
| Cloud execution receipts | ✅ Production mode requires typed receipts with canonical content binding; `--allow-synthetic-fixture` for testing only |
| Safe secret redaction | ✅ Centralised in `src/redaction.py` (`sanitise_command()`/`contains_exposed_secret()`), used by every wrapper/builder/publisher; detects `--name=value`, `--name value`, `NAME=value`, `name:value`, `Authorization: Bearer`, and raw HF-token literal forms — one shared `=`/`:` assignment grammar |
| Strict release-evidence deserialisation | ✅ Release paths reject unknown fields at every depth (path-qualified); permissive parsing is migration-only and cannot publish |
| D-drive base runtime | ✅ venv must be based on `D:\Forecasting-Tool-Local\python312`; `sys.executable`/`sys.base_prefix`/`pyvenv.cfg home` verified; no `py`/PATH bootstrap |
| Canonical Cloud template parity | ✅ `cloud_stage0_template.json` carries the 19 canonical test names; parity test runs (no skip) |
| Python installer verification | ✅ SHA-256 + Authenticode verification before execution |
| Shared recursive evidence validation (WP9) | ✅ `src/evidence_validation.py` |
| Shared D-drive storage policy (WP12) | ✅ `src/storage_policy.py`, `docs/development/storage_policy.md` |
| Bounded coordinator telemetry (WP1) | ✅ `deque(maxlen=256)`, `CoordinatorExecution` |
| Historical Chronos-2 local evidence (commit ee8f89...) | ✅ Collected prior |
| PR #18 evidence bundle | ✅ Invalidated, preserved for audit |
| PR #19 evidence invalidation | ✅ Complete |
| PR #20 coordinator integration | ✅ Complete |
| Gate B3 valid superseding evidence | ✅ Published 2026-08-05 (genuine bundle, commit `7831cb4`) |
| Community Cloud deployment (Gate C) | ✅ **COMPLETE** — final genuine evidence at commit `aa290c6f` (both token lifecycles on the same deployed commit; **18/19 verified** + `oversized_csv_rejected` platform-enforced; **two-session concurrency** and **coordinator timeout recovery (5 s)** genuinely re-measured); manifest `cloud_summary` populated with `evidence_cloud_stage0_20260808_130858_484438_4ca8249f.json` — see `docs/evidence/cloud_gate_c/README.md` |
| ADR-001 inference backend | ✅ Accepted (Choice A) — Cloud Gate C complete, Stage 0 complete — see `docs/adr_001_inference_backend.md` |
| Phase 1 data ingestion core | ✅ Merged (PR #13) but paused — not integrated |
| Phase 1 features | 🔜 After Stage 0 gates pass |
| Steps completed (current PR) | CI fail-closed (coverage rounding fix), explicit `evidence_origin` everywhere, sanitise-before-bind publisher pipeline, real receipt files in manifest, execution-wrapper/bundle compatibility, schema-level Cloud receipt + `CloudCollectionSession` binding, synthetic-mode fixes, `receipt_is_release_ready()` wired into schema validation, mutation tests, D-drive MCP/Graphify enforcement, colon-delimited secret detection (PR #27 P1), strict release deserialisation, D-drive base runtime enforcement, `workflow_dispatch` recovery trigger, correctness lint across `src/`/`scripts/`, canonical Cloud template parity — see "PR #27 review closure and release-readiness closure" below |
| MCP developer tooling | ✅ Optional, not functionally verified |

## Repository Structure

```
app.py                  # Streamlit entry point
pages/
    1_Forecast.py       # Stage 0 forecast page (lazy-loaded model)
    2_Methodology.py    # Documentation and methodology
src/
    config.py           # Centralised configuration
    schemas.py          # Canonical typed schemas with invariant validation
    telemetry.py        # Reusable telemetry helpers (memory, HF cache, evidence writing)
    benchmarking.py     # Stage 0 benchmark harness
    coordinator.py      # Process-wide inference coordinator (WP10)
    evidence_schemas.py # Typed evidence models (v2) with validation
    data_ingestion.py   # Phase 1 ingestion core (paused, not integrated)
    forecasting/
        base.py         # ForecastBackend protocol
        chronos2_adapter.py  # Chronos2Adapter class
scripts/
    chronos2_smoke_test.py       # Standalone smoke test
    run_stage0_benchmark.py      # Benchmark runner
    build_local_stage0_bundle.py # Bundle builder with validation (WP1)
    publish_evidence.py          # Sanitise, validate, copy, update manifest
    verify_evidence_manifest.py  # Manifest integrity checker (WP9)
    setup_local_windows.ps1     # Windows D: drive setup
    verify_environment.py       # Environment verification
tests/
    test_schemas.py              # Schema + validation tests
    test_adapter_contract.py     # Adapter tests with fake pipeline
    test_benchmarking.py         # Benchmark harness tests
    test_evidence.py             # Evidence schema, publisher, manifest, bundle tests
    test_ingestion.py            # Phase 1 ingestion tests (paused)
    fixtures/                    # Synthetic data fixtures
docs/
    evidence/stage0/             # Sanitised evidence artefacts + manifest
    stage_0_benchmark_report.md  # Stage 0 benchmark report (genuine Gate B3 evidence at commit 7831cb4)
    adr_001_inference_backend.md # ADR-001 — Accepted (Choice A) with documented limitations
    community_cloud_test_checklist.md  # Cloud testing checklist
    development/                 # MCP developer tooling (optional)
.github/workflows/
    ci.yml              # CI (unit tests, lint, coverage, evidence hash verify)
```

## Local Setup (Windows, D: drive)

### Prerequisites

- **D: drive** with sufficient free space
- The pinned Python 3.12.10 runtime installed directly into
  `D:\Forecasting-Tool-Local\python312` (the setup script downloads,
  SHA-256/Authenticode-verifies, and installs it there automatically). The
  project venv **must** be based on that D-drive interpreter — a venv
  created from a C-drive Python is not an approved runtime and is rejected
  by `verify_environment.py`.

### Installation (automated)

```powershell
# Run the setup script (creates everything on D: drive)
.\scripts\setup_local_windows.ps1
```

This script will:
1. Install the pinned Python 3.12.10 directly into `D:\Forecasting-Tool-Local\python312`
   (downloads, verifies SHA-256 and Authenticode, then installs — never
   uses `py` or a PATH Python as a bootstrap)
2. Create `D:\Forecasting-Tool-Local\` with venv, caches, temp, and benchmarks,
   using `D:\Forecasting-Tool-Local\python312\python.exe` to create the venv
3. Set all cache environment variables to D: drive
4. Install PyTorch (CPU), runtime deps, and dev deps (every pip command via
   the D-drive venv interpreter)
5. Verify the venv base interpreter (`sys.executable`, `sys.base_prefix`,
   `pyvenv.cfg home`) is the D-drive project Python
6. Run `scripts/verify_environment.py`

### Manual installation

```powershell
# Set environment variables (all D: drive, including Hub and Xet caches)
$env:PIP_CACHE_DIR = "D:\Forecasting-Tool-Local\cache\pip"
$env:HF_HOME = "D:\Forecasting-Tool-Local\cache\huggingface"
$env:HUGGINGFACE_HUB_CACHE = "D:\Forecasting-Tool-Local\cache\huggingface"
$env:HF_HUB_CACHE = "D:\Forecasting-Tool-Local\cache\huggingface\hub"
$env:HF_XET_CACHE = "D:\Forecasting-Tool-Local\cache\huggingface\xet"
$env:TRANSFORMERS_CACHE = "D:\Forecasting-Tool-Local\cache\transformers"
$env:TORCH_HOME = "D:\Forecasting-Tool-Local\cache\torch"
$env:TMP = "D:\Forecasting-Tool-Local\temp"
$env:TEMP = "D:\Forecasting-Tool-Local\temp"

# Create directories
New-Item -ItemType Directory -Force -Path D:\Forecasting-Tool-Local\venv, D:\Forecasting-Tool-Local\cache\pip, D:\Forecasting-Tool-Local\temp | Out-Null

# Create the virtual environment FROM THE D-DRIVE PYTHON (never `py`/PATH):
D:\Forecasting-Tool-Local\python312\python.exe -m venv D:\Forecasting-Tool-Local\venv

# Install dependencies (requirements.txt includes --extra-index-url for CPU-only PyTorch)
D:\Forecasting-Tool-Local\venv\Scripts\python.exe -m pip install -r requirements.txt
D:\Forecasting-Tool-Local\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

### Commands

```powershell
# Activate the D: drive environment (sets caches + activates venv)
.\scripts\activate_local_windows.ps1

# Run unit tests (no model download)
python -m pytest tests -v

# Run smoke test (first run downloads Chronos-2 ~500MB)
# Use --initial-cache-state download_cold for first-ever run on a machine
# Use --initial-cache-state process_cold_cached_weights when weights are cached
python scripts/chronos2_smoke_test.py --initial-cache-state process_cold_cached_weights

# Run benchmarks
python scripts/run_stage0_benchmark.py --initial-cache-state process_cold_cached_weights

# Launch Streamlit
python -m streamlit run app.py
```

## Chronos-2 Adapter

The `Chronos2Adapter` class in `src/forecasting/chronos2_adapter.py` implements the
`ForecastBackend` protocol and wraps `Chronos2Pipeline` from `chronos-forecasting`.

Key features:
- Dependency injection (accepts pre-built pipeline or callable provider)
- Lazy model loading (pipeline created on first `forecast()` call)
- Streaming forecast output conversion to canonical `ForecastResult`
- Runtime metadata capture (model ID, revision, package versions, timings)
- Safe error types (`ConfigurationError`, `ModelLoadError`, `InferenceError`, `ResultSchemaError`)

## Branch protection

The intended `main` branch protection policy requires:

- Pull request reviews before merging
- CI status checks to pass
- Resolved review threads
- Up-to-date branch

PR CI must be green before merging. Note that PR #8, PR #9, and PR #26 were
merged while review threads remained unresolved — either the repository
settings do not enforce the documented policy or the threads were created
after merge. The documentation here describes the required policy, which
should be independently verified against the GitHub repository settings.

A passing PR must satisfy all of the following before merge, not just a
green CI run:

- CI green (including the fail-closed coverage gate and targeted lint gate)
- Review completed
- Zero unresolved review conversations
- Branch up to date with `main`
- PR head SHA recorded in the PR description/commit trail
- Post-merge `main` CI (the push-triggered run for the exact merge commit)
  checked separately from the PR's own merge-ref run — a PR passing CI on
  its merge ref does not by itself prove the merge commit on `main` is green

`.github/workflows/ci.yml` triggers on both `push` to `main` and
`pull_request` against `main`, so the mechanism for a separate post-merge
run already exists; what has repeatedly been missing is someone actually
checking that run's result before treating a merge as final.

Push-to-main CI is configured but no post-merge commit had been verified on
`main` as of PR #26's merge — this is confirmed after each subsequent merge
(see below for this corrective PR's own record).

Genuine current-head local model evidence (Gates B2–B3) is published on
commit `7831cb4` (2026-08-05). **Cloud Gate C is COMPLETE**: final genuine
evidence was collected on 2026-08-08 at commit `aa290c6f` (both token
lifecycles, two-session concurrency, and coordinator timeout recovery
re-measured; 18/19 verified + `oversized_csv_rejected` platform-enforced;
see `docs/evidence/cloud_gate_c/`), and ADR-001 was accepted (Choice A)
with **no unresolved measurement limitations** — **Stage 0 is complete**.

## Remaining Stage 0 gates

| Gate | Requirement | Status | Sequence |
|------|-------------|--------|----------|
| A8 | Evidence and MCP-security closure | ✅ Merged (PR #10) | 1 |
| A9 | Evidence publication hardening | ✅ Merged (PR #11) | 2 |
| B2 | Current-head local evidence rerun | ✅ Completed (PR #12) | 3 |
| B3 | Current-head local evidence bundle | ✅ Genuine bundle published 2026-08-05 (commit `7831cb4`) — independently executed token-present run; supersedes invalidated PR #18 | 4 |
| C | Community Cloud technical spike | ✅ **COMPLETE** — final genuine evidence at commit `aa290c6f` (PR #38); both token lifecycles, concurrency + timeout recovery re-measured; 18/19 verified + `oversized_csv_rejected` platform-enforced | 5 |
| D | ADR-001 decision | ✅ Accepted (Choice A) — Cloud Gate C complete (PR #36 + final Gate C closure) | 6 |
| E | Phase 1 start | 🔜 Next — Stage 0 gates have passed; Phase 1 work resumes | 7 |

> **Correct sequence:** deploy to Cloud → collect evidence → decide ADR.
> The Cloud gate (C) is now complete and Stage 0 has passed, so Phase 1
> feature work resumes (Stage C: Phase 1 ingestion slice).

## Current status

- **Local evidence (Gate B2)**: Completed and committed. See `docs/evidence/stage0/`.
- **Local evidence bundle (Gate B3)**: **Valid — genuine bundle published
  2026-08-05** on commit `7831cb4`
  (`docs/evidence/stage0/evidence_local_stage0_bundle_20260805_171733_555681_2ce6345f.json`).
  It contains an independently executed token-present run (unique `run_id`
  and timestamps, exact pinned revision) plus genuine download-cold,
  process-cold, benchmark (4/4 scenarios, 10/10 rolling folds) and model
  artifact components, all bound to typed execution receipts, and passed
  `build_local_stage0_bundle.py` validation with 0 errors. This supersedes
  the invalidated PR #18 bundle (kept for audit — see
  `docs/evidence/stage0/evidence_manifest.json`), whose
  `runs.token_present_smoke` record was byte-for-byte identical to
  `runs.process_cold_smoke` with only `hf_token_present` and the token-result
  objects changed. `scripts/chronos2_smoke_test.py` and
  `scripts/build_local_stage0_bundle.py` require independently-provenanced
  token-path evidence (unique `run_id`, timestamps, matching revisions per
  attempted path) so a duplicated record is mechanically rejected.
- **Cloud evidence (Gate C)**: ✅ **COMPLETE — Stage 0 passed.** Final genuine
  collection at commit **`aa290c6f`** (2026-08-08, PR #38) on both token
  lifecycles of the exact same deployed commit: **18 of 19 required
  measurements verified** (incl. recoverable inference failure + configuration
  preservation) plus `oversized_csv_rejected` **platform-enforced**
  (rejection-before-parse verified; typed event not emittable — represented in
  the contract via `platform_enforced`). **two-session concurrency** proven at
  `dc3046fa` (Stage A fix) and re-captured at `aa290c6f`; **coordinator
  timeout recovery** genuinely re-measured at `aa290c6f` at the
  measured-justified 5 s queue timeout (timeout `317f3d11-…` + recovery
  `3b952e38-…` bound). Manifest `cloud_summary` populated with
  `docs/evidence/stage0/evidence_cloud_stage0_20260808_130858_484438_4ca8249f.json`
  (`cloud_stage0`, `success=True`, `evidence_origin=real_measurement`).
- **ADR-001**: ✅ Accepted (Choice A) — Cloud Gate C complete, **no unresolved
  measurement limitations**; Stage 0 is complete (2026-08-08).
- **Phase 1 ingestion**: Core module merged (PR #13) but not integrated with the
  Streamlit page. Stage 0 has now passed; Phase 1 feature work resumes (Stage C:
  Phase 1 ingestion slice).
- **Inference coordinator**: `src/coordinator.py` implements a bounded
  semaphore, request telemetry, and **explicitly separated timeout
  semantics**:
  - `queue_timeout_seconds` (default 5 s) bounds how long a *queued*
    request waits for the capacity-1 permit; on expiry it raises
    `CoordinatorTimeoutError` (a queue wait only — it never touches the
    backend). Justified by genuine measured Cloud durations (warm
    ~0.06-0.5 s, cold incl. model load ~6.4-8.7 s, max legitimate request
    ~8-9 s): it bounds the worst-case silent wait, stays above a normal
    warm request, and is genuinely inducible with a legitimate cold/max
    request.
  - `backend_execution_timeout_seconds` (default 900 s) is the
    execution-liveness watchdog: a backend call that never returns makes the
    coordinator **fail closed** (`health_state=poisoned`) and the permit is
    **not** released, so no second inference can enter a still-running
    shared pipeline until the application process is safely recycled
    (`BackendExecutionUnresponsiveError` / `CoordinatorPoisonedError`).
  The production Streamlit page (`pages/1_Forecast.py`) routes every
  forecast call through a process-cached `InferenceCoordinator.run(...)`.
  The UI busy state is an explicit active-request lifecycle
  (`request_id`/`started_at_utc`/`phase`) rather than a lone persistent
  boolean: it clears on every exit path (success, queue timeout, adapter
  error, unexpected error, telemetry failure) and a rerun identifies
  stale/orphaned state, so a session can never be permanently disabled.

> **Evidence manifest** contains the local Stage 0 bundle hash. CI verifies its
> integrity on every run — hash/schema verification passing does **not**
> imply the evidence is trustworthy release evidence; check `status` in
> `evidence_manifest.json` for entries marked `invalidated`. Cloud evidence
> entry remains null until Gate C. Direct dependency pins are not a complete
> lock — capture a lock file after Cloud success. Community Cloud may process
> `requirements.txt` with `uv` before falling back to `pip`.

## Stage 0 publication and CI integrity closure (PR #26)

PR #26 closed the receipt/evidence-integrity and CI gaps found in PR #25's
review (see PR #25 threads on `build_cloud_stage0_evidence.py`,
`evidence_schemas.py`, `publish_evidence.py`, and `telemetry.py`) and the
false-green coverage gate found in PR #25's own CI run. At the time it did
**not** collect real Stage 0 evidence — Gate B3 was invalid, Cloud Gate C
stayed pending, ADR-001 stayed provisional, and Phase 1 stayed paused; only
the mechanisms that would validate a future real evidence collection were
built and offline-contract-tested there. A genuine Gate B3 bundle was later
published on 2026-08-05 (see the Stage 0 gates table).

**Authoritative PR #26 CI results** (workflow run `30587158601`; the PR
description's "86.70%" coverage figure is stale — this is the verified log):

- 506 tests passed, 5 warnings
- Actual coverage: 86.34% (configured gate: 82%)
- Offline readiness verifier: 21/21 checks passed

**Two P1 findings were live at merge** (both review threads were unresolved
when PR #26 merged, verified via GitHub GraphQL):

1. `src/redaction.py` — `contains_exposed_secret()` used a ±20-character
   window allowlist, so a safe marker anywhere near a real credential (e.g.
   `HF_TOKEN=abcdef --token-state present`) suppressed the exposure instead
   of exempting only the matched value.
2. `src/evidence_schemas.py` — `CloudCollectionSession.validate()` did not
   require `deployed_commit`, and `CloudEvidence.validate()` never compared
   the session's `code_commit`/`deployed_commit` against the enclosing
   record, so a collection session describing a different deployment could
   still validate once its receipt digest was updated to match.

Both are fixed in the corrective PR described below, with regression tests
that reproduce the reviewer's exact examples.

Status tiers used below: **implemented** (code exists) → **offline
contract-tested** (pytest/readiness-script coverage against synthetic
fixtures, no model, no network) → **ready for real evidence collection**
(the mechanism has been proven against realistic fixtures and is wired
into the collection pipeline) → **real evidence collected** (a genuine
Stage 0/Cloud run has produced and published data through it) →
**Cloud Gate C passed** (Community Cloud measurements accepted).

| Mechanism | Status |
|---|---|
| CI coverage gate (fail-closed) | Offline contract-tested — `tests/test_ci_contract.py` reproduces the exact rounding bug and proves `--cov-precision=2` + the independent `coverage report` step close it; wired into `ci.yml` as two steps plus a third workflow-contract regression step |
| Publication order (sanitise → bind → publish) | Offline contract-tested — `scripts/publish_evidence.py::main()` proves sanitiser idempotence and re-validates the sanitised object before writing; `tests/test_publish_evidence_e2e.py` exercises the full CLI path end to end |
| Cloud receipt binding (schema-level) | Offline contract-tested — `CloudEvidence.validate()` itself (not just the builder script) requires and verifies each receipt's canonical digest against its bound result, plus the new `CloudCollectionSession` record `collection_receipt` binds to; `tests/test_cloud_builder.py` |
| Synthetic-evidence isolation | Offline contract-tested — every nested receipt's `evidence_origin` must agree with its parent record; production mode rejects a synthetic receipt even without `--allow-synthetic-fixture`; publisher/verifier reject any `synthetic_fixture` release entry |
| Receipt manifest tracking | Offline contract-tested — `publish_evidence.py` writes each receipt as its own real JSON file with a byte-accurate SHA-256, never a synthetic `embedded_in_<bundle>` filename |
| Command redaction | Offline contract-tested — `src/redaction.py` used by every wrapper/builder/publisher; `tests/test_redaction.py` covers `--name=value`, `--name value`, env assignments, and Authorization headers |
| D-drive runtime enforcement (incl. MCP/Graphify) | Offline contract-tested — `tests/test_ddrive_setup.py` diffs `setup_local_windows.ps1`'s directory/env-var declarations against `src/storage_policy.py` in both directions; `-PythonPath` outside `D:\Forecasting-Tool-Local` is rejected; the one C-drive touchpoint (bootstrap interpreter for the initial `venv` creation) is documented and never used again after that step |

None of the above have real evidence collected against them yet, and Cloud
Gate C has not been attempted. The gated follow-on work (local Stage 0
evidence rerun, then Community Cloud Gate C) is unblocked by PR #26 but was
out of scope for it.

## PR #26 review closure and release-readiness closure

This corrective PR fixes the two P1 findings that were live when PR #26
merged (see above), adds behavioral readiness checks for both, and closes
several related gaps found while doing that work. At the time it did **not**
collect any real Stage 0 evidence, deploy to Community Cloud, change the
model ID or pinned revision, or resume Phase 1 — Gate B3 was invalid, Cloud
Gate C stayed pending, ADR-001 stayed provisional, and Phase 1 stayed
paused. (A genuine Gate B3 bundle was later published on 2026-08-05.)

Fixes:

- **P1-1 (exact-match secret detection)**: `src/redaction.py`'s
  `contains_exposed_secret()` no longer uses a surrounding-text window to
  decide whether a match is exempt — only the matched value/argument
  itself is checked against a safe-marker allowlist (`***REDACTED***`,
  `[REDACTED]`, `<redacted>`). `tests/test_redaction.py` and
  `tests/test_redaction_contract.py` reproduce the reviewer's exact
  examples and prove every production receipt-validation path
  (`ExecutionReceipt.validate()`, `receipt_is_release_ready()`, the local
  bundle builder's `_validate_receipt_binding()`, and the readiness
  verifier) rejects the same unsafe command.
- **P1-2 (collection-session identity binding)**: `CloudCollectionSession.validate()`
  now requires `deployed_commit` (previously optional) and rejects a real
  session whose `code_commit` disagrees with its own `deployed_commit`.
  `CloudEvidence.validate()` now additionally compares the collection
  session's `code_commit`/`deployed_commit` against the enclosing record's
  own fields, and validates session timestamps as parsed, timezone-aware
  datetimes rather than lexical string comparison. `tests/test_evidence.py::TestCollectionSessionBinding`
  mutates session commit, deployed commit, top-level commits, receipt
  commit, receipt digest, and session ID independently — each fails
  validation.
- **Readiness verifier**: expanded from 21 to 25 checks — 4 new behavioral
  checks cover a collection session naming another commit, an empty
  `deployed_commit`, a collection receipt with the wrong commit identity,
  and that a legitimately sanitised session/receipt pair still validates;
  the existing secret-redaction check (`[9/25]`) gained the exact P1-1
  reproduction strings.
- **Installer integrity bug found while verifying the D-drive runtime
  path**: the SHA-256 pinned in `scripts/setup_local_windows.ps1` for the
  Python 3.12.10 installer never matched the real python.org release
  artifact (verified against the official published MD5 and a valid
  Authenticode signature from the Python Software Foundation) — every run
  of the setup script would have failed this check. Corrected, with a
  regression test pinning the verified value so it can't silently revert.
- **Targeted lint debt**: fixed all F811 (redefinition), F541 (f-string
  without placeholders), F841 (unused local variable), and W605 (invalid
  escape sequence) findings in `src/redaction.py`, `src/evidence_schemas.py`,
  `scripts/verify_stage0_evidence_readiness.py`,
  `scripts/run_stage0_benchmark.py`, and `tests/test_evidence.py` — the
  files this PR touches. Two of those findings were genuine test bugs, not
  just style: a duplicate `test_app_restart_occurred_rejected` definition
  silently shadowed the first (removed), and `test_missing_rolling_folds_rejected`
  never called `.validate()` or asserted anything (fixed to actually
  exercise the fold-count check). Repo-wide F811/F541/F841/W605 debt exists
  in files this PR doesn't touch (`build_cloud_stage0_evidence.py`,
  `build_local_stage0_bundle.py`, `chronos2_smoke_test.py`,
  `install_simple.py`, `publish_evidence.py`, `benchmarking.py`,
  `data_ingestion.py`, `test_benchmarking.py`, `test_producer_contract.py`)
  and is intentionally left for a separate maintenance PR. CI now runs a
  fail-closed `flake8 --select=F811,F541,F841,W605` step scoped to the four
  modules this PR can hold at zero, alongside the existing fatal-only
  (`E9,F63,F7,F82`) gate over the whole tree.

**This PR's own CI results:** _(to be filled in the pull request description
after CI runs, per the same governance requirement above.)_

## PR #27 review closure and release-readiness closure

This corrective PR fixes the PR #27 P1 finding (colon-delimited secret
detection) that was marked resolved on GitHub but never actually fixed, and
closes the remaining Stage 0 release-readiness gaps. At the time it did
**not** collect any real Stage 0 evidence, deploy to Community Cloud,
change the model ID or pinned revision, or resume Phase 1 — Gate B3 was
invalid, Cloud Gate C stayed pending, ADR-001 stayed provisional, and Phase
1 stayed paused. (A genuine Gate B3 bundle was later published on
2026-08-05.)

Fixes:

- **P1 (colon-delimited secret detection)**: `src/redaction.py` now unifies
  detection and sanitisation around one assignment grammar (`=` or `:`,
  optional surrounding whitespace), so `api_key:secret`, `api-key: secret`,
  `APIKEY:secret`, `password:hunter2`, `HF_TOKEN:abcdef`, and
  `--api-key:secret` are all detected and redacted. A safe marker exempts
  only the matched value. `tests/test_redaction.py::TestColonDelimitedSecrets`
  and `tests/test_redaction_contract.py::TestColonDelimitedContractAcrossReceiptPaths`
  cover every production receipt path (`ExecutionReceipt.validate()`,
  `receipt_is_release_ready()`, `ReceiptContext`, `run_with_receipt()`,
  local bundle validation, Cloud evidence validation, publisher
  validation, readiness verification).
- **Strict release-evidence deserialisation**: `evidence_from_dict(..., strict=True)`
  rejects unknown fields at every depth with a path-qualified error; the
  publisher, bundle builder, Cloud builder, recursive validator, and
  manifest verifier all use strict mode. Permissive parsing remains only as
  an explicit migration mode that cannot publish or update the release
  manifest.
- **D-drive base runtime**: `verify_ddrive_runtime()` verifies
  `sys.executable`, `sys.prefix`, `sys.base_prefix`, and `pyvenv.cfg home`;
  the setup script no longer uses a `py`/PATH bootstrap and installs the
  pinned Python directly into `D:\Forecasting-Tool-Local\python312`.
- **Post-merge CI observability**: `workflow_dispatch` added for explicit
  recovery/diagnostics; a workflow-contract test asserts the required
  triggers. The push-to-main run on the exact merge commit remains the
  authoritative gate.
- **Correctness lint broadened**: fail-closed flake8 now enforces
  `E9,F63,F7,F82,F402,F541,F811,F841,W605` across `src/` and `scripts/`
  (all pre-existing violations fixed). `E501` line length and broad
  formatting are not blockers.
- **Canonical Cloud template parity**: `cloud_stage0_template.json` now
  carries the 19 canonical test names and the parity test runs instead of
  skipping; the readiness verifier checks template↔registry↔checklist
  parity.
- **Autonomous merge governance**: `docs/development/autonomous_merge.md`
  (exact merge state machine) and
  `docs/development/pr_review_completion_checklist.md` (per-finding
  resolution evidence contract).

**This PR's own CI results:** _(to be filled in the pull request description
after CI runs, per the same governance requirement above.)_

## Developer MCP integrations (optional)

This repository includes optional configuration for **Model Context
Protocol (MCP)** servers — developer tooling that gives a coding assistant
(e.g. Claude Code) read access to repository/CI state, current library
documentation, a disposable browser for inspecting the running Streamlit
app, and Hugging Face Hub metadata while you work.

MCP is **not required to run the forecasting application** and is not a
Python or Streamlit dependency. See
[`docs/development/mcp_setup.md`](docs/development/mcp_setup.md) for setup
and [`docs/development/mcp_usage_policy.md`](docs/development/mcp_usage_policy.md)
for the read-only-by-default usage policy. Unauthenticated templates live
in [`tools/mcp/`](tools/mcp/).

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).