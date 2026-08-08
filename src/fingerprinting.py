"""Deterministic data fingerprinting for Phase 1 (Slice 4).

Computes a stable SHA-256 over the canonical time-series data — the row
records of a ``ForecastTask.historical_data``, or raw timestamp/value arrays.

The fingerprint follows the same canonical-JSON rules as the repository's
evidence digests (sorted keys at every nesting level, fixed separators, no
whitespace) so that semantically identical data always produces the same
fingerprint regardless of dict insertion order, tuple-vs-list shapes or
numpy-vs-python scalar types, and any semantic mutation (a changed value,
timestamp, or an added/removed row) changes it.

Unlike the strict evidence digests (``canonical_evidence_sha256``), which
reject non-finite floats, data fingerprints *normalise* missing values:
``NaN`` (and ``±Infinity``) are encoded as distinct canonical markers, so a
series containing missing target values still fingerprints deterministically.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from src.schemas import ForecastTask


# Canonical markers for non-finite floats (collision-safe dicts, so a literal
# string value can never collide with a missing-value marker).
_NAN_MARKER: dict[str, Any] = {"__fp_nan__": True}
_POS_INF_MARKER: dict[str, Any] = {"__fp_inf__": 1}
_NEG_INF_MARKER: dict[str, Any] = {"__fp_inf__": -1}


# ---------------------------------------------------------------------------
# Canonical serialisation
# ---------------------------------------------------------------------------


def _canonical(obj: Any) -> Any:
    """Recursively normalise an object for deterministic JSON encoding."""
    if isinstance(obj, dict):
        return {
            str(k): _canonical(v)
            for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(obj, (list, tuple)):
        return [_canonical(item) for item in obj]
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat()
    if isinstance(obj, np.generic):
        return _canonical(obj.item())
    if isinstance(obj, float):
        if math.isnan(obj):
            return _NAN_MARKER
        if math.isinf(obj):
            return _POS_INF_MARKER if obj > 0 else _NEG_INF_MARKER
        return obj
    if isinstance(obj, (int, str, bool)) or obj is None:
        return obj
    # Unknown scalar (e.g. a UUID or enum) — make it deterministic.
    return str(obj)


def canonical_json_bytes(data: Any) -> bytes:
    """UTF-8 canonical JSON bytes for ``data``.

    Rules mirror ``src.evidence_schemas.canonical_evidence_sha256``: sorted
    keys at every level, fixed ``(',', ':')`` separators, no whitespace,
    ASCII-escaped output.  Non-finite floats have already been normalised by
    ``_canonical``, so ``allow_nan=False`` is safe here.
    """
    canonical = _canonical(data)
    return json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


def compute_data_fingerprint(records: Iterable[Mapping[str, Any]]) -> str:
    """Deterministic SHA-256 over canonical row records (list of dicts).

    Returns a lowercase 64-character hex digest.
    """
    return hashlib.sha256(canonical_json_bytes(list(records))).hexdigest()


def fingerprint_forecast_task(task: ForecastTask) -> str:
    """Fingerprint a task's canonical historical data.

    ``ForecastTask`` construction already rejects empty ``historical_data``,
    so the records are guaranteed non-empty here.
    """
    return compute_data_fingerprint(task.historical_data)


def fingerprint_series(
    timestamps: Sequence,
    values: Sequence[float],
) -> str:
    """Fingerprint a raw series as canonical ``{timestamp, target}`` records.

    Raises ``ValueError`` when the two sequences have different lengths.
    """
    if len(timestamps) != len(values):
        raise ValueError(
            f"timestamps ({len(timestamps)}) and values ({len(values)}) "
            "lengths differ"
        )
    records = [
        {"timestamp": ts, "target": val} for ts, val in zip(timestamps, values)
    ]
    return compute_data_fingerprint(records)


__all__ = (
    "canonical_json_bytes",
    "compute_data_fingerprint",
    "fingerprint_forecast_task",
    "fingerprint_series",
)
