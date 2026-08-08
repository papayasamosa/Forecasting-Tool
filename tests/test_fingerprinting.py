"""Tests for deterministic data fingerprinting — Phase 1 Slice 4.

Covers ``src.fingerprinting`` (canonical serialisation, SHA-256 fingerprints,
task/series helpers and the adapter wiring).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.fingerprinting import (
    canonical_json_bytes,
    compute_data_fingerprint,
    fingerprint_forecast_task,
    fingerprint_series,
)
from src.schemas import ForecastMode, ForecastTask


def _records() -> list[dict]:
    return [
        {"timestamp": "2024-01-01T00:00:00", "target": 100.5},
        {"timestamp": "2024-01-08T00:00:00", "target": 102.25},
        {"timestamp": "2024-01-15T00:00:00", "target": 101.0},
    ]


class TestCanonicalJsonBytes:
    def test_returns_utf8_bytes(self):
        out = canonical_json_bytes({"a": 1})
        assert isinstance(out, bytes)
        assert out == b'{"a":1}'

    def test_deterministic(self):
        assert canonical_json_bytes({"b": 2, "a": 1}) == canonical_json_bytes({"a": 1, "b": 2})

    def test_sorted_keys_recursively(self):
        assert canonical_json_bytes({"z": {"y": 1, "x": 2}}) == b'{"z":{"x":2,"y":1}}'


class TestComputeDataFingerprint:
    def test_returns_64_hex(self):
        fp = compute_data_fingerprint(_records())
        assert isinstance(fp, str)
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_deterministic(self):
        assert compute_data_fingerprint(_records()) == compute_data_fingerprint(_records())

    def test_key_order_insensitive(self):
        a = compute_data_fingerprint([{"timestamp": "2024-01-01", "target": 1.0}])
        b = compute_data_fingerprint([{"target": 1.0, "timestamp": "2024-01-01"}])
        assert a == b

    def test_tuple_list_equivalent(self):
        a = compute_data_fingerprint([("ts", 1.0)])
        b = compute_data_fingerprint([["ts", 1.0]])
        assert a == b

    def test_value_change_changes_fingerprint(self):
        base = _records()
        changed = [dict(r, target=r["target"] + 1.0) for r in base]
        assert compute_data_fingerprint(base) != compute_data_fingerprint(changed)

    def test_timestamp_change_changes_fingerprint(self):
        base = _records()
        changed = list(base)
        changed[0] = dict(changed[0], timestamp="2024-01-02T00:00:00")
        assert compute_data_fingerprint(base) != compute_data_fingerprint(changed)

    def test_added_row_changes_fingerprint(self):
        base = _records()
        extra = base + [{"timestamp": "2024-01-22T00:00:00", "target": 99.0}]
        assert compute_data_fingerprint(base) != compute_data_fingerprint(extra)

    def test_numpy_scalar_equivalent_to_float(self):
        a = compute_data_fingerprint([{"timestamp": "2024-01-01", "target": 1.5}])
        b = compute_data_fingerprint([{"timestamp": "2024-01-01", "target": np.float64(1.5)}])
        assert a == b

    def test_timestamp_equivalent_to_iso_string(self):
        a = compute_data_fingerprint([{"timestamp": pd.Timestamp("2024-01-01"), "target": 1.0}])
        b = compute_data_fingerprint([{"timestamp": "2024-01-01T00:00:00", "target": 1.0}])
        assert a == b

    def test_nan_fingerprints_deterministically(self):
        recs = [{"timestamp": "2024-01-01", "target": np.nan}]
        assert compute_data_fingerprint(recs) == compute_data_fingerprint(recs)

    def test_nan_differs_from_value(self):
        a = compute_data_fingerprint([{"timestamp": "2024-01-01", "target": np.nan}])
        b = compute_data_fingerprint([{"timestamp": "2024-01-01", "target": 1.0}])
        assert a != b

    def test_nan_position_sensitive(self):
        a = compute_data_fingerprint(
            [{"timestamp": "2024-01-01", "target": np.nan}, {"timestamp": "2024-01-02", "target": 1.0}]
        )
        b = compute_data_fingerprint(
            [{"timestamp": "2024-01-01", "target": 1.0}, {"timestamp": "2024-01-02", "target": np.nan}]
        )
        assert a != b

    def test_infinity_normalised(self):
        assert compute_data_fingerprint([{"target": float("inf")}]) == compute_data_fingerprint(
            [{"target": float("inf")}]
        )
        assert compute_data_fingerprint([{"target": float("inf")}]) != compute_data_fingerprint(
            [{"target": float("-inf")}]
        )


class TestFingerprintForecastTask:
    def _task(self) -> ForecastTask:
        return ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=tuple(_records()),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=3,
        )

    def test_fingerprints_task_data(self):
        task = self._task()
        fp = fingerprint_forecast_task(task)
        assert len(fp) == 64
        assert fp == compute_data_fingerprint(task.historical_data)

    def test_empty_records_deterministic(self):
        # Task construction forbids empty data, but the lower-level helper
        # must still fingerprint an empty record set deterministically.
        fp = compute_data_fingerprint([])
        assert len(fp) == 64
        assert fp == compute_data_fingerprint([])


class TestFingerprintSeries:
    def test_matches_record_fingerprint(self):
        timestamps = pd.date_range("2024-01-01", periods=3, freq="W")
        values = [1.0, 2.0, 3.0]
        series_fp = fingerprint_series(timestamps, values)
        records_fp = compute_data_fingerprint(
            [
                {"timestamp": t, "target": v}
                for t, v in zip(timestamps, values)
            ]
        )
        assert series_fp == records_fp

    def test_deterministic(self):
        ts = pd.date_range("2024-01-01", periods=3, freq="D")
        vals = [1.0, 2.0, 3.0]
        assert fingerprint_series(ts, vals) == fingerprint_series(ts, vals)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="lengths differ"):
            fingerprint_series([1, 2, 3], [1.0, 2.0])


class TestAdapterWiring:
    def test_runtime_metadata_fingerprint_populated(self):
        """The adapter must set a non-empty data fingerprint on RunMetadata."""
        from src.forecasting.chronos2_adapter import Chronos2Adapter

        class _FakePipeline:
            model_id = "amazon/chronos-2-test"
            model_revision = "fake-revision-001"

            def predict_df(self, input_df, **kwargs):
                prediction_length = kwargs.get("prediction_length", 13)
                quantile_levels = kwargs.get("quantile_levels", [0.1, 0.5, 0.9])
                last_ts = pd.to_datetime(input_df["timestamp"].iloc[-1])
                dates = list(
                    pd.date_range(start=last_ts, periods=prediction_length + 1, freq="D")[1:]
                )
                rows = []
                for i, d in enumerate(dates):
                    row = {
                        "item_id": "series_1",
                        "timestamp": d,
                        "predictions": float(i + 1),
                    }
                    for q in quantile_levels:
                        row[str(q)] = float(i + 1)
                    rows.append(row)
                return pd.DataFrame(rows)

        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=tuple(_records()),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=3,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        adapter = Chronos2Adapter(pipeline_or_provider=_FakePipeline())
        result = adapter.forecast(task)
        fp = result.runtime_metadata.data_fingerprint
        assert isinstance(fp, str)
        assert len(fp) == 64
        assert fp == fingerprint_forecast_task(task)

