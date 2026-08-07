# pragma: no cover
"""Shared process-level cached runtime objects for the Streamlit pages.

Defined in a shared, non-page module (the leading underscore keeps it out
of the multipage sidebar) so the Forecast page and the Cloud Diagnostics
page resolve the SAME process-cached backend, inference coordinator, and
request-telemetry store.  ``st.cache_resource`` keys on the qualified name
of the decorated function, so a single definition here is the only way for
two page scripts to share one instance per process.
"""
from __future__ import annotations

import streamlit as st

from src.config import (
    COORDINATOR_BACKEND_EXECUTION_TIMEOUT_SECONDS,
    COORDINATOR_CAPACITY,
    COORDINATOR_QUEUE_TIMEOUT_SECONDS,
)
from src.cloud_diagnostics import RequestTelemetryStore
from src.coordinator import InferenceCoordinator
from src.forecasting.chronos2_adapter import Chronos2Adapter


@st.cache_resource
def get_forecast_backend() -> Chronos2Adapter:
    """Process-cached Chronos2Adapter (model loads lazily on first forecast)."""
    return Chronos2Adapter()


@st.cache_resource
def get_coordinator() -> InferenceCoordinator:
    """Process-cached InferenceCoordinator (one per process, like the backend)."""
    return InferenceCoordinator(
        capacity=COORDINATOR_CAPACITY,
        queue_timeout_seconds=COORDINATOR_QUEUE_TIMEOUT_SECONDS,
        backend_execution_timeout_seconds=COORDINATOR_BACKEND_EXECUTION_TIMEOUT_SECONDS,
    )


@st.cache_resource
def get_telemetry_store() -> RequestTelemetryStore:
    """Process-cached bounded request-telemetry store (never raw payloads)."""
    return RequestTelemetryStore()
