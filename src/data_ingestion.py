"""Data ingestion pipeline for Phase 1.

Handles CSV parsing, column mapping, file-size checks, SHA-256 identity,
and basic data preparation. Produces canonical ``ForecastTask`` objects
ready for validation and forecasting.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from io import BytesIO, StringIO
from typing import Any

import pandas as pd

from src.config import MAX_UPLOAD_SIZE_BYTES
from src.schemas import ForecastMode, ForecastTask


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class IngestedData:
    """Result of parsing and identifying uploaded data."""
    df: pd.DataFrame
    sha256: str
    columns: list[str]
    row_count: int
    file_size_bytes: int


@dataclass
class ColumnMapping:
    """Mapping from upload columns to canonical names."""
    timestamp: str = "timestamp"
    target: str = "target"
    item_id: str | None = None


@dataclass
class IngestionResult:
    """Complete result of the ingestion pipeline.

    ``task`` is None if ingestion failed validation.
    """
    data: IngestedData | None = None
    mapping: ColumnMapping | None = None
    task: ForecastTask | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    original_row_count: int = 0
    retained_row_count: int = 0
    truncated: bool = False


# ---------------------------------------------------------------------------
# Upload helpers
# ---------------------------------------------------------------------------


def check_file_size(size_bytes: int) -> str | None:
    """Return an error message if the file exceeds the maximum size."""
    if size_bytes > MAX_UPLOAD_SIZE_BYTES:
        return (
            f"File exceeds the {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB limit "
            f"({size_bytes / 1024 / 1024:.1f} MB)."
        )
    return None


def compute_sha256(file_bytes: bytes) -> str:
    """Compute SHA-256 hex digest of raw file bytes."""
    return hashlib.sha256(file_bytes).hexdigest()


def parse_csv_bytes(file_bytes: bytes) -> pd.DataFrame:
    """Parse raw CSV bytes into a DataFrame.

    Raises ``ValueError`` if the CSV is empty or unparseable.
    """
    try:
        df = pd.read_csv(BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError(f"Could not parse CSV: {exc}") from exc
    if df.empty or len(df.columns) == 0:
        raise ValueError("CSV has no columns or is empty.")
    return df


def detect_column_mapping(
    df: pd.DataFrame,
    *,
    preferred_timestamp: str | None = None,
    preferred_target: str | None = None,
) -> ColumnMapping:
    """Auto-detect column mapping from a DataFrame.

    Looks for common timestamp and target column names.
    Falls back to first and second columns if no match is found.
    """
    ts_lower = {c.lower(): c for c in df.columns}
    ts_col = "timestamp"
    target_col = "target"

    # Use preferred values if provided and present
    if preferred_timestamp and preferred_timestamp in df.columns:
        ts_col = preferred_timestamp
    elif "timestamp" in ts_lower:
        ts_col = ts_lower["timestamp"]
    elif "date" in ts_lower:
        ts_col = ts_lower["date"]
    elif "datetime" in ts_lower:
        ts_col = ts_lower["datetime"]
    else:
        ts_col = df.columns[0]

    if preferred_target and preferred_target in df.columns:
        target_col = preferred_target
    elif "target" in ts_lower:
        target_col = ts_lower["target"]
    elif "value" in ts_lower:
        target_col = ts_lower["value"]
    elif "y" in ts_lower:
        target_col = ts_lower["y"]
    else:
        # Pick the first column that is not the timestamp column
        remaining = [c for c in df.columns if c != ts_col]
        target_col = remaining[0] if remaining else df.columns[0]

    return ColumnMapping(timestamp=ts_col, target=target_col)


def ingest_upload(
    file_bytes: bytes,
    *,
    mapping: ColumnMapping | None = None,
) -> IngestedData:
    """Parse and identify uploaded bytes.

    Parameters
    ----------
    file_bytes : bytes
        Raw CSV file bytes.
    mapping : ColumnMapping or None
        Optional explicit column mapping. Auto-detected if None.

    Returns
    -------
    IngestedData
        Parsed data with SHA-256 identity and metadata.
    """
    sha256 = compute_sha256(file_bytes)
    df = parse_csv_bytes(file_bytes)
    return IngestedData(
        df=df,
        sha256=sha256,
        columns=list(df.columns),
        row_count=len(df),
        file_size_bytes=len(file_bytes),
    )


# ---------------------------------------------------------------------------
# ForecastTask builder
# ---------------------------------------------------------------------------


def prepare_dataframe(
    df: pd.DataFrame,
    mapping: ColumnMapping,
    *,
    context_window_cap: int | None = None,
) -> tuple[pd.DataFrame, list[str], int, int]:
    """Extract, parse and cap columns from a raw DataFrame.

    Returns (working_df, warnings, original_rows, retained_rows).
    """
    warnings: list[str] = []
    ts_col = mapping.timestamp
    target_col = mapping.target

    # Validate columns exist
    if ts_col not in df.columns:
        raise ValueError(f"Timestamp column '{ts_col}' not found in data. Available: {list(df.columns)}")
    if target_col not in df.columns:
        raise ValueError(f"Target column '{target_col}' not found in data. Available: {list(df.columns)}")

    # Select only needed columns
    cols_to_use = [ts_col, target_col]
    if mapping.item_id and mapping.item_id in df.columns:
        cols_to_use.append(mapping.item_id)
    working_df = df[cols_to_use].copy()

    # Parse timestamps
    try:
        working_df[ts_col] = pd.to_datetime(working_df[ts_col])
    except Exception as exc:
        raise ValueError(f"Could not parse timestamps in column '{ts_col}': {exc}") from exc

    # Detect NaT values
    nat_mask = working_df[ts_col].isna()
    nat_count = nat_mask.sum()
    if nat_count > 0:
        total = len(working_df)
        if nat_count == total:
            raise ValueError(
                f"The timestamp column '{ts_col}' contains no valid dates "
                f"({nat_count} of {total} rows are blank or unparseable)."
            )
        else:
            raise ValueError(
                f"The timestamp column '{ts_col}' has {nat_count} invalid "
                f"row(s) out of {total}. Remove or fix the invalid timestamps."
            )

    # Sort chronologically
    working_df = working_df.sort_values(ts_col).reset_index(drop=True)
    original_rows = len(working_df)

    if original_rows == 0:
        raise ValueError(
            "The selected columns produced zero valid rows. "
            "Check that the timestamp column contains parseable dates."
        )

    # Context capping
    retained_rows = original_rows
    if context_window_cap is not None and original_rows > context_window_cap:
        working_df = working_df.iloc[-context_window_cap:].reset_index(drop=True)
        retained_rows = len(working_df)
        warnings.append(
            f"Context truncated from {original_rows} to {context_window_cap} rows "
            f"(retaining the {context_window_cap} most recent observations)."
        )

    return working_df, warnings, original_rows, retained_rows


def build_forecast_task(
    df: pd.DataFrame,
    mapping: ColumnMapping,
    *,
    prediction_length: int = 13,
    quantile_levels: tuple[float, ...] = (0.1, 0.5, 0.9),
    frequency: str = "",
    context_window_cap: int | None = None,
) -> ForecastTask:
    """Build a canonical ``ForecastTask`` from prepared data.

    Parameters
    ----------
    df : pd.DataFrame
        Raw (unprepared) DataFrame from upload or demo data.
    mapping : ColumnMapping
        Column name mapping.
    prediction_length : int
        Forecast horizon.
    quantile_levels : tuple[float, ...]
        Requested quantiles.
    frequency : str
        Pandas frequency string (auto-inferred if empty).
    context_window_cap : int or None
        Maximum context rows to retain.

    Returns
    -------
    ForecastTask
        Validated task ready for the backend.
    """
    from src.config import CONTEXT_WINDOW_CAP as DEFAULT_CAP

    cap = context_window_cap if context_window_cap is not None else DEFAULT_CAP
    working_df, warnings, original_rows, retained_rows = prepare_dataframe(
        df, mapping, context_window_cap=cap,
    )

    records = tuple(working_df.to_dict("records"))

    try:
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=records,
            timestamp_column=mapping.timestamp,
            target_columns=(mapping.target,),
            prediction_length=prediction_length,
            quantile_levels=quantile_levels,
            frequency=frequency,
            context_window_cap=None,  # already capped
        )
    except ValueError as exc:
        raise ValueError(f"ForecastTask configuration error: {exc}") from exc

    return task
