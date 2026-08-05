# pragma: no cover
"""Streamlit page: Forecast — Stage 0 (not yet Phase 1).

The Chronos-2 model is loaded only when the user clicks "Run Forecast".
The backend and the inference coordinator are both cached at the process
level via ``st.cache_resource``; every forecast call is routed through
``InferenceCoordinator.run`` so overlapping sessions queue behind a bounded
semaphore instead of racing the shared cached backend directly.

Memory-conscious design (WP4):
- Only a SHA-256 identity of uploaded bytes is retained, not the raw bytes.
- Selected columns only are used for the forecast.
- Raw bytes are released immediately after parsing.
- The full parsed DataFrame remains cached across reruns (keyed by hash).
- Context cap is applied chronologically before row-record conversion.
- Truncation warnings are shown and propagated to RunMetadata.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sys
import uuid
from io import StringIO, BytesIO

import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import (  # noqa: E402
    CONTEXT_WINDOW_CAP,
    COORDINATOR_CAPACITY,
    COORDINATOR_TIMEOUT_SECONDS,
    MAX_UPLOAD_SIZE_BYTES,
    QUANTILE_MIN,
    QUANTILE_MAX,
)
from src.schemas import (  # noqa: E402
    ForecastMode,
    ForecastTask,
    WarningCode,
)
from src.forecasting.chronos2_adapter import (  # noqa: E402
    Chronos2Adapter,
    AdapterError,
)
from src.coordinator import (  # noqa: E402
    InferenceCoordinator,
    CoordinatorTimeoutError,
)
from src.telemetry import (  # noqa: E402
    current_rss_mb,
    deployed_commit,
    process_peak_rss_mb,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Forecast — Chronos-2", page_icon="📈", layout="wide")

# ---------------------------------------------------------------------------
# Constants (use config as source of truth)
# ---------------------------------------------------------------------------
# MAX_UPLOAD_SIZE_BYTES imported from src.config

# ---------------------------------------------------------------------------
# Helpers (defined BEFORE their first use to avoid NameError)
# ---------------------------------------------------------------------------

def _build_demo_data() -> pd.DataFrame:
    """Return a synthetic weekly time-series fixture (104 periods)."""
    import numpy as np
    rng = np.random.default_rng(seed=42)
    t = np.arange(104)
    values = 100 + 0.05 * t + 5 * np.sin(2 * np.pi * t / 52) + rng.normal(0, 2, size=104)
    dates = pd.date_range("2022-01-03", periods=104, freq="W")
    return pd.DataFrame({"timestamp": dates, "target": values})


@st.cache_resource
def _get_forecast_backend() -> Chronos2Adapter:
    """Return a process-cached Chronos2Adapter (model loads on first forecast)."""
    logger.info("Creating Chronos2Adapter (process-level cache).")
    return Chronos2Adapter()


def _resolve_backend() -> Chronos2Adapter:
    """Return the backend to use for this run.

    Test-only seam: if st.session_state["_test_backend_override"] is set, it
    is returned instead of the process-cached backend. This exists because
    this module's name starts with a digit, so unittest.mock.patch cannot
    target it (pkgutil.resolve_name rejects "pages.1_Forecast" as an invalid
    dotted name), and Streamlit's AppTest executes this script outside
    normal import machinery anyway. Production code paths never set this
    session_state key.
    """
    override = st.session_state.get("_test_backend_override")
    if override is not None:
        return override
    return _get_forecast_backend()


@st.cache_resource
def _get_coordinator() -> InferenceCoordinator:
    """Return a process-cached InferenceCoordinator (one per process, like the backend)."""
    logger.info("Creating InferenceCoordinator (process-level cache).")
    return InferenceCoordinator(capacity=COORDINATOR_CAPACITY, timeout_seconds=COORDINATOR_TIMEOUT_SECONDS)


def _resolve_coordinator() -> InferenceCoordinator:
    """Return the coordinator to use for this run.

    Test-only seam mirroring ``_resolve_backend``: if
    st.session_state["_test_coordinator_override"] is set, it is returned
    instead of the process-cached coordinator. Production code paths never
    set this session_state key.
    """
    override = st.session_state.get("_test_coordinator_override")
    if override is not None:
        return override
    return _get_coordinator()


def _parse_csv_bytes(file_bytes: bytes) -> pd.DataFrame:
    """Parse uploaded CSV bytes once and return a DataFrame."""
    return pd.read_csv(BytesIO(file_bytes))


# ---------------------------------------------------------------------------
# Session state (configuration and results, NOT the model)
# ---------------------------------------------------------------------------
_DEFAULT_STATE = {
    "run_id": "",
    "forecast_result": None,
    "error_message": "",
    "is_running": False,
    "cached_df": None,           # parsed DataFrame reused across reruns
    "cached_df_hash": "",        # SHA-256 of uploaded bytes (identity only)
    "cached_columns": [],
    "last_queue_seconds": 0.0,   # coordinator queue wait for the most recent run
}
for k, v in _DEFAULT_STATE.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------
st.title("🔮 Chronos-2 Forecast")
st.markdown("_Stage 0 — Technical Feasibility Spike | Not yet Phase 1_")

with st.sidebar:
    st.header("Configuration")

    data_option = st.radio("Data source", ["Use demo data", "Upload CSV"], index=0)

    uploaded_file = None
    ts_col = "timestamp"
    target_col = "target"

    # Reset cached data when switching data sources
    if "last_data_option" not in st.session_state or st.session_state.last_data_option != data_option:
        st.session_state.cached_df = None
        st.session_state.cached_df_hash = ""
        st.session_state.last_data_option = data_option

    if data_option == "Upload CSV":
        uploaded_file = st.file_uploader("Choose a CSV file", type=["csv"])
        if uploaded_file is not None:
            # Check size before reading (WP4: keep pre-parse cap)
            uploaded_file.seek(0, os.SEEK_END)
            size = uploaded_file.tell()
            uploaded_file.seek(0)
            if size > MAX_UPLOAD_SIZE_BYTES:
                st.error(f"File exceeds the {MAX_UPLOAD_SIZE_BYTES // (1024*1024)} MB limit ({size / 1024 / 1024:.1f} MB).")
                uploaded_file = None
                st.session_state.cached_df = None
                st.session_state.cached_df_hash = ""
            else:
                # Read bytes once, compute identity hash, then release bytes
                file_bytes = uploaded_file.read()
                file_hash = hashlib.sha256(file_bytes).hexdigest()
                if st.session_state.cached_df_hash != file_hash:
                    st.session_state.cached_df_hash = file_hash
                    try:
                        st.session_state.cached_df = _parse_csv_bytes(file_bytes)
                        st.session_state.cached_columns = st.session_state.cached_df.columns.tolist()
                    except Exception:
                        st.error("Could not parse CSV. Please check the file format.")
                        st.session_state.cached_df = None
                        st.session_state.cached_df_hash = ""
                    finally:
                        # Release raw bytes immediately after parsing
                        del file_bytes
                else:
                    # Release bytes even when hash matches (no need to retain)
                    del file_bytes

                if st.session_state.cached_df is not None:
                    cols = st.session_state.cached_columns
                    ts_col = st.selectbox("Timestamp column", cols, index=0, key="ts_col")
                    target_col = st.selectbox("Target column", cols, index=min(1, len(cols) - 1), key="target_col")

    st.markdown("---")
    horizon = st.number_input("Forecast horizon (periods)", min_value=1, max_value=1024, value=13, step=1)
    quantiles_str = st.text_input("Quantile levels (comma-separated)", value="0.1, 0.5, 0.9")
    st.markdown("---")
    run_button = st.button("🚀 Run Forecast", type="primary", use_container_width=True,
                          disabled=st.session_state.is_running)

# ---------------------------------------------------------------------------
# Data preview (no model loading here)
# ---------------------------------------------------------------------------
st.subheader("📊 Data")

if data_option == "Use demo data":
    df = _build_demo_data()
    st.info("Using built-in synthetic weekly data (104 periods).")
    st.dataframe(df.head(10), use_container_width=True)
elif st.session_state.cached_df is not None:
    df = st.session_state.cached_df
    st.success(f"Loaded {len(df)} rows, {len(df.columns)} columns.")
    st.dataframe(df.head(10), use_container_width=True)
else:
    df = None
    st.info("Upload a CSV or use demo data to continue.")

# ---------------------------------------------------------------------------
# Run forecast (lazy — model not loaded until first click)
# ---------------------------------------------------------------------------
if run_button and df is not None and not st.session_state.is_running:
    st.session_state.is_running = True
    st.session_state.error_message = ""
    st.session_state.forecast_result = None

    # Parse quantiles using config constants
    try:
        q_levels = [float(q.strip()) for q in quantiles_str.split(",") if q.strip()]
        if not q_levels:
            raise ValueError("No quantile levels provided.")
        for q in q_levels:
            if q < QUANTILE_MIN or q > QUANTILE_MAX:
                raise ValueError(f"Quantile must be between {QUANTILE_MIN} and {QUANTILE_MAX} inclusive, got {q}")
    except ValueError as e:
        st.error(f"Invalid quantile levels: {e}")
        st.session_state.is_running = False
        st.stop()

    # Block identical timestamp and target column selections (WP6)
    if ts_col == target_col:
        st.error("Timestamp and target columns must be different.")
        st.session_state.is_running = False
        st.stop()

    # Use selected columns only (WP4: reduce memory before row-record expansion)
    if ts_col in df.columns and target_col in df.columns:
        working_df = df[[ts_col, target_col]].copy()
    else:
        st.error(f"Selected columns '{ts_col}' and/or '{target_col}' not found in data.")
        st.session_state.is_running = False
        st.stop()

    # Parse timestamps and sort chronologically (WP6: keep latest observations)
    try:
        working_df[ts_col] = pd.to_datetime(working_df[ts_col])
    except Exception as exc:
        logger.warning(f"Timestamp parse failed in column '{ts_col}': {type(exc).__name__}")
        st.error(f"Could not parse timestamps in column '{ts_col}'. Check the date format.")
        st.session_state.is_running = False
        st.stop()

    # ------------------------------------------------------------------
    # Missing timestamp detection (P0-3): detect NaT values after
    # parsing.  Block the run before sorting or materialisation so rows
    # containing invalid timestamps never reach the backend.
    # ------------------------------------------------------------------
    nat_mask = working_df[ts_col].isna()
    nat_count = nat_mask.sum()
    if nat_count > 0:
        total_rows = len(working_df)
        if nat_count == total_rows:
            st.error(
                f"The timestamp column '{ts_col}' contains no valid dates "
                f"({nat_count} of {total_rows} rows are blank or unparseable). "
                "Check that the column contains parseable date values."
            )
        else:
            st.error(
                f"The timestamp column '{ts_col}' has {nat_count} invalid "
                f"row(s) out of {total_rows}. "
                "Remove or fix the invalid timestamps and try again."
            )
        st.session_state.is_running = False
        st.stop()

    working_df = working_df.sort_values(ts_col).reset_index(drop=True)

    # ------------------------------------------------------------------
    # Empty-data guard (P0-2): check before any iloc access. A
    # headers-only CSV or all-NaN timestamp column yields zero rows.
    # ------------------------------------------------------------------
    original_rows = len(working_df)
    if original_rows == 0:
        st.error("The selected columns produced zero valid rows. Check that the timestamp column contains parseable dates.")
        st.session_state.is_running = False
        st.stop()

    # ------------------------------------------------------------------
    # Preprocessing metadata — recorded BEFORE materialisation so that
    # large datasets are capped before Python dict expansion (P0-1).
    # ------------------------------------------------------------------
    date_range_start = str(working_df[ts_col].iloc[0])
    date_range_end = str(working_df[ts_col].iloc[-1])

    # Cap context BEFORE converting to dict records
    retained_rows = original_rows
    retained_start = date_range_start
    if CONTEXT_WINDOW_CAP is not None and original_rows > CONTEXT_WINDOW_CAP:
        working_df = working_df.iloc[-CONTEXT_WINDOW_CAP:].reset_index(drop=True)
        retained_rows = len(working_df)
        retained_start = str(working_df[ts_col].iloc[0])

    # Only materialise retained rows
    records = tuple(working_df.to_dict("records"))

    # Build task with context_window_cap set to None (already capped)
    try:
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=records,
            timestamp_column=ts_col,
            target_columns=(target_col,),
            prediction_length=int(horizon),
            quantile_levels=tuple(q_levels),
            context_window_cap=None,
        )
    except ValueError as e:
        st.error(f"Configuration error: {e}")
        st.session_state.is_running = False
        st.stop()

    # Get or create the process-cached backend and coordinator (model loads
    # lazily on first forecast; the coordinator serialises concurrent
    # sessions' inference calls through a bounded semaphore).
    try:
        backend = _resolve_backend()
        coordinator = _resolve_coordinator()
        request_id = str(uuid.uuid4())
        # Run forecast under the coordinator so overlapping sessions queue
        # rather than racing the shared cached backend directly.
        with st.spinner("Running Chronos-2 forecast (may load model on first call, or queue behind another request)..."):
            exec_record = coordinator.run(backend.forecast, task, request_id=request_id)
            result = exec_record.result
            # Attach preprocessing metadata captured before materialisation
            import dataclasses
            old_meta = result.runtime_metadata
            new_meta = dataclasses.replace(
                old_meta,
                preprocessing_original_rows=original_rows,
                preprocessing_retained_rows=retained_rows,
                preprocessing_retained_start=retained_start,
                preprocessing_date_range_start=date_range_start,
                preprocessing_date_range_end=date_range_end,
            )
            result = dataclasses.replace(result, runtime_metadata=new_meta)
            st.session_state.forecast_result = result
            st.session_state.run_id = result.run_id
            # Sanitised queue-time telemetry from the execution record (no
            # full-history scan).
            st.session_state.last_queue_seconds = exec_record.request_record.get("queue_seconds", 0.0)
    except CoordinatorTimeoutError:
        st.session_state.error_message = (
            "The forecasting service is busy handling another request and did not "
            "become available in time. Please try again in a moment."
        )
        logger.warning("Coordinator timeout waiting for inference slot", exc_info=True)
    except AdapterError as e:
        st.session_state.error_message = str(e)
        logger.warning("Forecast failed", exc_info=True)
    except Exception:
        st.session_state.error_message = "An unexpected error occurred. Please check your data and try again."
        logger.error("Unexpected forecast error", exc_info=True)

    st.session_state.is_running = False

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
if st.session_state.forecast_result:
    result = st.session_state.forecast_result
    meta = result.runtime_metadata
    label = "cold" if meta.model_was_loaded_this_run else "warm"

    st.subheader("✅ Forecast Complete")

    # Show warnings (WP2, WP3: deduplicate; render truncation independently)
    all_warnings = list(result.warnings) + list(meta.warnings)
    seen: set[str] = set()
    deduped_warnings: list[str] = []
    for w in all_warnings:
        if w not in seen:
            seen.add(w)
            deduped_warnings.append(w)
    if deduped_warnings:
        with st.expander("⚠️ Warnings", expanded=bool(deduped_warnings)):
            for w in deduped_warnings:
                st.warning(w)

    # Show preprocessing truncation details independently of runtime warnings
    # (P0-3: truncation must be visible even when there are no runtime warnings).
    if meta.preprocessing_original_rows > meta.preprocessing_retained_rows:
        st.info(
            f"Context truncated: {meta.preprocessing_original_rows} original rows "
            f"→ {meta.preprocessing_retained_rows} retained "
            f"(data from {meta.preprocessing_date_range_start} to {meta.preprocessing_date_range_end}, "
            f"retained from {meta.preprocessing_retained_start})."
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Run ID", result.run_id)
    c2.metric("Horizon", meta.prediction_length)
    c3.metric("Backend", f"{result.backend_name} ({label})")
    c4.metric("Inference", f"{meta.inference_seconds:.2f}s")

    # Show timing breakdown
    with st.expander("⏱ Timing & model details", expanded=False):
        st.write(f"- **Queue wait:** {st.session_state.last_queue_seconds:.3f}s")
        st.write(f"- **Model load:** {meta.model_load_seconds:.3f}s")
        st.write(f"- **Inference:** {meta.inference_seconds:.3f}s")
        st.write(f"- **Result conversion:** {meta.result_conversion_seconds:.3f}s")
        st.write(f"- **Total runtime:** {meta.total_runtime_seconds:.3f}s")
        st.write(f"- **Pipeline reused:** {meta.pipeline_reused}")
        st.write(f"- **Model revision:** {result.model_revision}")
        st.write(f"- **Context rows used:** {meta.context_rows_used}")
        # WP7: resource evidence — memory must be measurable from the public
        # app (stdlib-only reads so the Cloud runtime needs no extra deps).
        st.write(f"- **Process peak RSS:** {process_peak_rss_mb():.1f} MB")
        st.write(f"- **Current RSS:** {current_rss_mb():.1f} MB")
        # WP6: deployment identity — best-effort git commit of the running
        # checkout (file-based resolution; resolvable when the runtime
        # ships .git metadata).
        st.write(f"- **Deployed commit:** {deployed_commit() or 'not available'}")

    st.subheader("📋 Forecast Table")
    rows_df = pd.DataFrame(result.forecast_rows)
    display_cols = [c for c in rows_df.columns if c not in ("run_id", "target_name")]
    st.dataframe(rows_df[display_cols], use_container_width=True)

    csv_buffer = StringIO()
    rows_df.to_csv(csv_buffer, index=False)
    st.download_button("Download forecast CSV", data=csv_buffer.getvalue(),
                       file_name=f"forecast_{result.run_id}.csv", mime="text/csv")

elif st.session_state.error_message:
    st.error(st.session_state.error_message)
    st.info("Your configuration has been preserved. Adjust and try again.")
