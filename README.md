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
| CI (GitHub Actions) | ✅ Fail-closed: `--cov-precision=2` + independent `coverage report` gate + workflow-contract regression test, threshold 82% (actual ~86%), `src.storage_policy`/`src.redaction` included |
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
| Safe secret redaction | ✅ Centralised in `src/redaction.py` (`sanitise_command()`/`contains_exposed_secret()`), used by every wrapper/builder/publisher; detects `--name=value`, `--name value`, `NAME=value`, and `Authorization: Bearer` forms |
| Python installer verification | ✅ SHA-256 + Authenticode verification before execution |
| Shared recursive evidence validation (WP9) | ✅ `src/evidence_validation.py` |
| Shared D-drive storage policy (WP12) | ✅ `src/storage_policy.py`, `docs/development/storage_policy.md` |
| Bounded coordinator telemetry (WP1) | ✅ `deque(maxlen=256)`, `CoordinatorExecution` |
| Historical Chronos-2 local evidence (commit ee8f89...) | ✅ Collected prior |
| PR #18 evidence bundle | ✅ Invalidated, preserved for audit |
| PR #19 evidence invalidation | ✅ Complete |
| PR #20 coordinator integration | ✅ Complete |
| Gate B3 valid superseding evidence | ❌ Invalid — pending genuine rerun |
| Community Cloud deployment (Gate C) | ⏳ Pending — checklist remains blank |
| ADR-001 inference backend | ⏳ Provisionally accepted pending Cloud Gate C |
| Phase 1 data ingestion core | ✅ Merged (PR #13) but paused — not integrated |
| Phase 1 features | 🔜 After Stage 0 gates pass |
| Steps completed (current PR) | CI fail-closed (coverage rounding fix), explicit `evidence_origin` everywhere, sanitise-before-bind publisher pipeline, real receipt files in manifest, execution-wrapper/bundle compatibility, schema-level Cloud receipt + `CloudCollectionSession` binding, synthetic-mode fixes, `receipt_is_release_ready()` wired into schema validation, mutation tests, D-drive MCP/Graphify enforcement — see "Stage 0 publication and CI integrity closure" below |
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
    stage_0_benchmark_report.md  # Benchmark report (needs current-head rerun)
    adr_001_inference_backend.md # Provisional — pending Cloud evidence
    community_cloud_test_checklist.md  # Cloud testing checklist
    development/                 # MCP developer tooling (optional)
.github/workflows/
    ci.yml              # CI (unit tests, lint, coverage, evidence hash verify)
```

## Local Setup (Windows, D: drive)

### Prerequisites

- **Python 3.12** — [Download from python.org](https://www.python.org/downloads/)
- **D: drive** with sufficient free space

### Installation (automated)

```powershell
# Run the setup script (creates everything on D: drive)
.\scripts\setup_local_windows.ps1
```

This script will:
1. Verify Python 3.12 is available
2. Create `D:\Forecasting-Tool-Local\` with venv, caches, temp, and benchmarks
3. Set all cache environment variables to D: drive
4. Install PyTorch (CPU), runtime deps, and dev deps
5. Run `scripts/verify_environment.py`

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

# Create virtual environment (adjust Python path if needed)
py -3.12 -m venv D:\Forecasting-Tool-Local\venv

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

Real-model evidence (Gates B2–D) has not yet been collected on the current head.

## Remaining Stage 0 gates

| Gate | Requirement | Status | Sequence |
|------|-------------|--------|----------|
| A8 | Evidence and MCP-security closure | ✅ Merged (PR #10) | 1 |
| A9 | Evidence publication hardening | ✅ Merged (PR #11) | 2 |
| B2 | Current-head local evidence rerun | ✅ Completed (PR #12) | 3 |
| B3 | Current-head local evidence bundle | ❌ Invalidated (PR #18) — fabricated token-present record; genuine rerun required | 4 |
| C | Community Cloud technical spike | ⏳ Pending — needs completion | 5 |
| D | ADR-001 decision | ⏳ Provisionally accepted, pending Gate C | 6 |
| E | Phase 1 start | 🔜 Partially started (ingestion core merged) but on hold until Stage 0 passes | 7 |

> **Correct sequence:** deploy to Cloud → collect evidence → decide ADR.
> Phase 1 ingestion core was merged before Stage 0 passed. Additional Phase 1
> feature work is paused until the Cloud gate is completed.

## Current status

- **Local evidence (Gate B2)**: Completed and committed. See `docs/evidence/stage0/`.
- **Local evidence bundle (Gate B3, PR #18)**: **Invalidated.** The published
  bundle's `runs.token_present_smoke` record is byte-for-byte identical to
  `runs.process_cold_smoke` (same timestamps, timings, RSS) — only
  `hf_token_present` and the token-result objects were changed. It is not an
  independently executed token-present run; the PR #18 commit message itself
  states `HF_TOKEN` was unavailable and token-present evidence was omitted,
  which contradicts the bundle's `token_present_smoke.success=true`. The file
  is kept for audit (see `docs/evidence/stage0/evidence_manifest.json`,
  `status: "invalidated"`) but must not be treated as passing Gate B3.
  `scripts/chronos2_smoke_test.py` and `scripts/build_local_stage0_bundle.py`
  now emit and require independently-provenanced token-path evidence
  (unique `run_id`, timestamps, matching revisions per attempted path) so a
  duplicated record like this is mechanically rejected going forward. A
  genuine token-present rerun and superseding bundle are still required.
- **Cloud evidence (Gate C)**: Not yet completed. The Community Cloud checklist
  is still empty. This is the current blocker, in addition to the Gate B3 rerun.
- **ADR-001**: Provisionally accepted pending Cloud Gate C. Not finally accepted.
- **Phase 1 ingestion**: Core module merged (PR #13) but not integrated with the
  Streamlit page. No additional Phase 1 features will be added until Stage 0 passes.
- **Inference coordinator**: `src/coordinator.py` implements a bounded semaphore
  and request telemetry. The production Streamlit page (`pages/1_Forecast.py`)
  now routes every forecast call through a process-cached
  `InferenceCoordinator.run(...)` instead of calling `backend.forecast(task)`
  directly, so overlapping sessions queue behind the semaphore and a
  `CoordinatorTimeoutError` surfaces as a recoverable, configuration-preserving
  error. Cloud concurrency evidence collected against this page will now be
  meaningful.

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
false-green coverage gate found in PR #25's own CI run. It did **not**
collect any real Stage 0 evidence — Gate B3 stayed invalid, Cloud Gate C
stayed pending, ADR-001 stayed provisional, and Phase 1 stayed paused; only
the mechanisms that will validate a future real evidence collection were
built and offline-contract-tested there.

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
several related gaps found while doing that work. It does **not** collect
any real Stage 0 evidence, deploy to Community Cloud, change the model ID
or pinned revision, or resume Phase 1 — Gate B3 stays invalid, Cloud Gate C
stays pending, ADR-001 stays provisional, and Phase 1 stays paused.

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