"""Tests for the Phase 1 data ingestion module.

No model weights are downloaded during these tests.
"""
from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

from src.data_ingestion import (
    DuplicateTimestampError,
    IngestedData,
    ColumnMapping,
    IngestionResult,
    check_file_size,
    compute_sha256,
    parse_csv_bytes,
    detect_column_mapping,
    ingest_upload,
    prepare_dataframe,
    build_forecast_task,
    run_ingestion_pipeline,
)
from src.config import MAX_UPLOAD_SIZE_BYTES
from src.schemas import ErrorCode, WarningCode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_csv_bytes(rows: int = 20, include_item_id: bool = False) -> bytes:
    rng = np.random.default_rng(seed=42)
    dates = pd.date_range("2024-01-01", periods=rows, freq="W")
    df = pd.DataFrame({"timestamp": dates, "target": 100 + rng.normal(0, 5, size=rows)})
    if include_item_id:
        df["item_id"] = "series_1"
    return df.to_csv(index=False).encode("utf-8")


def _make_empty_csv_bytes() -> bytes:
    return b"timestamp,target\n"


def _make_bad_timestamp_csv_bytes() -> bytes:
    return b"timestamp,target\nnot_a_date,1.0\n2024-01-01,2.0\n,3.0"


# ---------------------------------------------------------------------------
# File size checks
# ---------------------------------------------------------------------------


class TestCheckFileSize:
    def test_accepts_small_file(self):
        assert check_file_size(1024) is None

    def test_rejects_oversized_file(self):
        err = check_file_size(MAX_UPLOAD_SIZE_BYTES + 1)
        assert err is not None
        assert "exceeds" in err.lower()

    def test_accepts_exact_limit(self):
        assert check_file_size(MAX_UPLOAD_SIZE_BYTES) is None


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------


class TestParseCsvBytes:
    def test_parses_valid_csv(self):
        csv_bytes = _make_csv_bytes(10)
        df = parse_csv_bytes(csv_bytes)
        assert len(df) == 10
        assert "timestamp" in df.columns
        assert "target" in df.columns

    def test_rejects_empty_csv(self):
        with pytest.raises(ValueError):
            parse_csv_bytes(b"")
        with pytest.raises(ValueError):
            parse_csv_bytes(b"timestamp,target\n")

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            parse_csv_bytes(b"this is not csv data at all")


# ---------------------------------------------------------------------------
# SHA-256
# ---------------------------------------------------------------------------


class TestComputeSha256:
    def test_returns_hex_string(self):
        h = compute_sha256(b"test data")
        assert isinstance(h, str)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self):
        assert compute_sha256(b"hello") == compute_sha256(b"hello")

    def test_differs_for_different_data(self):
        assert compute_sha256(b"data1") != compute_sha256(b"data2")


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------


class TestDetectColumnMapping:
    def test_detects_timestamp_and_target(self):
        df = pd.DataFrame({"timestamp": [1], "target": [2]})
        m = detect_column_mapping(df)
        assert m.timestamp == "timestamp"
        assert m.target == "target"

    def test_detects_date_column(self):
        df = pd.DataFrame({"date": [1], "value": [2]})
        m = detect_column_mapping(df)
        assert m.timestamp == "date"
        assert m.target == "value"

    def test_falls_back_to_first_columns(self):
        df = pd.DataFrame({"col_a": [1], "col_b": [2]})
        m = detect_column_mapping(df)
        assert m.timestamp == "col_a"
        assert m.target == "col_b"

    def test_case_insensitive_match(self):
        df = pd.DataFrame({"Timestamp": [1], "Target": [2]})
        m = detect_column_mapping(df)
        assert m.timestamp == "Timestamp"
        assert m.target == "Target"

    def test_preferred_names_used(self):
        df = pd.DataFrame({"ts": [1], "val": [2]})
        m = detect_column_mapping(df, preferred_timestamp="ts", preferred_target="val")
        assert m.timestamp == "ts"
        assert m.target == "val"


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


class TestIngestUpload:
    def test_returns_ingested_data(self):
        csv_bytes = _make_csv_bytes(20)
        result = ingest_upload(csv_bytes)
        assert isinstance(result, IngestedData)
        assert result.row_count == 20
        assert len(result.sha256) == 64
        assert "timestamp" in result.columns
        assert result.file_size_bytes == len(csv_bytes)

    def test_raises_on_empty(self):
        with pytest.raises(ValueError):
            ingest_upload(b"")

    def test_accepts_explicit_mapping(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        result = ingest_upload(csv_bytes, mapping=ColumnMapping(timestamp="a", target="b"))
        assert result.row_count == 1


# ---------------------------------------------------------------------------
# DataFrame preparation
# ---------------------------------------------------------------------------


class TestPrepareDataframe:
    def test_basic_preparation(self):
        df = pd.DataFrame({
            "timestamp": ["2024-01-01", "2024-01-08", "2024-01-15"],
            "target": [10.0, 20.0, 30.0],
        })
        mapping = ColumnMapping(timestamp="timestamp", target="target")
        working_df, warns, orig, retained = prepare_dataframe(df, mapping)
        assert orig == 3
        assert retained == 3
        assert len(warns) == 0
        assert list(working_df.columns) == ["timestamp", "target"]

    def test_chronological_sort(self):
        df = pd.DataFrame({
            "timestamp": ["2024-01-15", "2024-01-01", "2024-01-08"],
            "target": [30.0, 10.0, 20.0],
        })
        mapping = ColumnMapping(timestamp="timestamp", target="target")
        working_df, *_ = prepare_dataframe(df, mapping)
        assert list(working_df["target"]) == [10.0, 20.0, 30.0]

    def test_context_capping(self):
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=100, freq="D"),
            "target": list(range(100)),
        })
        mapping = ColumnMapping(timestamp="timestamp", target="target")
        working_df, warns, orig, retained = prepare_dataframe(df, mapping, context_window_cap=10)
        assert orig == 100
        assert retained == 10
        assert len(warns) == 1
        assert "truncated" in warns[0].lower()
        assert len(working_df) == 10
        # Should retain the LAST 10 rows
        assert list(working_df["target"]) == list(range(90, 100))

    def test_rejects_missing_columns(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        mapping = ColumnMapping(timestamp="x", target="y")
        with pytest.raises(ValueError, match="not found"):
            prepare_dataframe(df, mapping)

    def test_rejects_bad_timestamps(self):
        csv_bytes = _make_bad_timestamp_csv_bytes()
        df = pd.read_csv(pd.io.common.BytesIO(csv_bytes))
        mapping = ColumnMapping(timestamp="timestamp", target="target")
        with pytest.raises(ValueError):
            prepare_dataframe(df, mapping)

    def test_rejects_all_nat_timestamps(self):
        csv_bytes = _make_empty_csv_bytes()
        df = pd.read_csv(pd.io.common.BytesIO(csv_bytes))
        mapping = ColumnMapping(timestamp="timestamp", target="target")
        with pytest.raises(ValueError, match="zero valid rows"):
            prepare_dataframe(df, mapping)

    def test_rejects_zero_rows_after_parse(self):
        df = pd.DataFrame({"timestamp": pd.to_datetime([]), "target": []})
        mapping = ColumnMapping(timestamp="timestamp", target="target")
        with pytest.raises(ValueError, match="zero valid rows"):
            prepare_dataframe(df, mapping)


# ---------------------------------------------------------------------------
# ForecastTask builder
# ---------------------------------------------------------------------------


class TestBuildForecastTask:
    def test_builds_valid_task(self):
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=20, freq="W"),
            "target": list(range(20)),
        })
        mapping = ColumnMapping(timestamp="timestamp", target="target")
        task = build_forecast_task(df, mapping, prediction_length=5)
        assert task.prediction_length == 5
        assert task.mode.value == "standard_univariate"
        assert len(task.historical_data) == 20

    def test_context_capping(self):
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=100, freq="D"),
            "target": list(range(100)),
        })
        mapping = ColumnMapping(timestamp="timestamp", target="target")
        task = build_forecast_task(df, mapping, prediction_length=5, context_window_cap=10)
        assert len(task.historical_data) == 10

    def test_quantile_levels_preserved(self):
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=20, freq="W"),
            "target": list(range(20)),
        })
        mapping = ColumnMapping(timestamp="timestamp", target="target")
        task = build_forecast_task(df, mapping, prediction_length=5, quantile_levels=(0.05, 0.5, 0.95))
        assert task.quantile_levels == (0.05, 0.5, 0.95)


# ---------------------------------------------------------------------------
# Duplicate timestamp detection (Phase 1 remediation)
# ---------------------------------------------------------------------------


class TestDuplicateTimestampDetection:
    def _dup_df(self) -> pd.DataFrame:
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=5, freq="D"),
            "target": [10.0, 20.0, 30.0, 40.0, 50.0],
        })
        return pd.concat(
            [df, df.iloc[[1]]], ignore_index=True
        ).sort_values("timestamp").reset_index(drop=True)

    def test_prepare_dataframe_raises_duplicate_error(self):
        df = self._dup_df()
        mapping = ColumnMapping(timestamp="timestamp", target="target")
        with pytest.raises(DuplicateTimestampError) as excinfo:
            prepare_dataframe(df, mapping)
        message = str(excinfo.value)
        assert "duplicate" in message.lower()
        # Phase 1 contract: detailed remediation guidance.
        assert "aggregate" in message.lower() or "re-upload" in message.lower()
        # The duplicated timestamp value is named.
        assert "2024-01-02" in message

    def test_build_forecast_task_raises_on_duplicates(self):
        df = self._dup_df()
        mapping = ColumnMapping(timestamp="timestamp", target="target")
        with pytest.raises(DuplicateTimestampError):
            build_forecast_task(df, mapping)

    def test_clean_data_passes(self):
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=5, freq="D"),
            "target": [10.0, 20.0, 30.0, 40.0, 50.0],
        })
        mapping = ColumnMapping(timestamp="timestamp", target="target")
        working_df, *_ = prepare_dataframe(df, mapping)
        assert len(working_df) == 5


# ---------------------------------------------------------------------------
# End-to-end ingestion pipeline
# ---------------------------------------------------------------------------


class TestRunIngestionPipeline:
    def _df(self, rows: int = 20) -> pd.DataFrame:
        rng = np.random.default_rng(seed=7)
        return pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=rows, freq="W"),
            "target": 100 + rng.normal(0, 5, size=rows),
        })

    def test_valid_data_builds_task(self):
        df = self._df()
        result = run_ingestion_pipeline(df, ColumnMapping(timestamp="timestamp", target="target"))
        assert isinstance(result, IngestionResult)
        assert result.task is not None
        assert result.report is not None
        assert result.report.is_blocking is False
        assert result.errors == []
        assert result.original_row_count == 20
        assert result.retained_row_count == 20
        assert result.truncated is False

    def test_frequency_auto_inferred(self):
        df = self._df()
        result = run_ingestion_pipeline(df, ColumnMapping(timestamp="timestamp", target="target"))
        assert result.task.frequency == "W"

    def test_explicit_frequency_preserved(self):
        df = self._df()
        result = run_ingestion_pipeline(
            df, ColumnMapping(timestamp="timestamp", target="target"), frequency="D"
        )
        assert result.task.frequency == "D"

    def test_duplicates_blocking_task_none(self):
        df = self._df()
        dup = df.iloc[[1]].copy()
        df = pd.concat([df, dup], ignore_index=True).sort_values("timestamp").reset_index(drop=True)
        result = run_ingestion_pipeline(df, ColumnMapping(timestamp="timestamp", target="target"))
        assert result.task is None
        assert result.report is not None
        assert result.report.is_blocking is True
        assert result.errors, "expected an error message"
        assert any(
            i.code == ErrorCode.DUPLICATE_TIMESTAMPS.value for i in result.report.errors
        )

    def test_all_missing_target_blocking(self):
        df = self._df()
        df["target"] = np.nan
        result = run_ingestion_pipeline(df, ColumnMapping(timestamp="timestamp", target="target"))
        assert result.task is None
        assert any(
            i.code == ErrorCode.MISSING_TARGET_VALUES.value for i in result.report.errors
        )

    def test_partial_missing_target_warns_but_builds(self):
        df = self._df()
        df.loc[3, "target"] = np.nan
        result = run_ingestion_pipeline(df, ColumnMapping(timestamp="timestamp", target="target"))
        assert result.task is not None
        assert any(
            i.code == WarningCode.MISSING_TARGET_VALUES.value for i in result.report.warnings
        )

    def test_short_history_warns_but_builds(self):
        df = self._df(rows=5)
        result = run_ingestion_pipeline(df, ColumnMapping(timestamp="timestamp", target="target"))
        assert result.task is not None
        assert any(
            i.code == WarningCode.SHORT_HISTORY.value for i in result.report.warnings
        )

    def test_constant_series_warns_but_builds(self):
        df = self._df()
        df["target"] = 9.0
        result = run_ingestion_pipeline(df, ColumnMapping(timestamp="timestamp", target="target"))
        assert result.task is not None
        assert any(
            i.code == WarningCode.ZERO_OR_NEAR_ZERO.value for i in result.report.warnings
        )

    def test_missing_column_blocking(self):
        df = self._df().drop(columns=["target"])
        result = run_ingestion_pipeline(df, ColumnMapping(timestamp="timestamp", target="target"))
        assert result.task is None
        assert result.report.is_blocking is True
        assert result.errors

    def test_truncation_warning_and_flag(self):
        df = self._df(rows=100)
        result = run_ingestion_pipeline(
            df, ColumnMapping(timestamp="timestamp", target="target"), context_window_cap=10
        )
        assert result.task is not None
        assert result.truncated is True
        assert result.retained_row_count == 10
        assert result.original_row_count == 100
        assert any("truncated" in w.lower() for w in result.warnings)

    def test_custom_mapping(self):
        df = self._df().rename(columns={"timestamp": "ts", "target": "val"})
        result = run_ingestion_pipeline(df, ColumnMapping(timestamp="ts", target="val"))
        assert result.task is not None
        assert result.task.timestamp_column == "ts"
        assert result.task.target_columns == ("val",)

