# pragma: no cover
"""Streamlit page: Cloud Diagnostics — safe operational metadata export.

This is the public, read-only diagnostics surface for Cloud Gate C
collection.  It exposes an allowlisted typed snapshot (no secrets, no
payloads, no filesystem paths), a deterministic JSON download with its
canonical digest, and deliberate collection-session controls (begin /
finalise) that take no secret input.

Security boundary (WP12):
- Only the allowlisted ``CloudRuntimeDiagnostics`` schema is rendered and
  exported — never an environment dump.
- ``HF_TOKEN`` is exposed only as a boolean (``hf_token_present``).
- No uploaded data, target values, forecast values, cookies, request
  headers, hostnames, usernames, home directories, or repository paths.
- No mutation or administrative action; no credentials required to read.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cloud_diagnostics import (  # noqa: E402
    build_collection_receipt,
    build_collection_session_record,
    build_public_diagnostics_export,
    is_exact_commit_sha,
)
from pages._cloud_runtime import (  # noqa: E402
    get_coordinator,
    get_forecast_backend,
    get_telemetry_store,
)

st.set_page_config(
    page_title="Cloud Diagnostics — Chronos-2",
    page_icon="🩺",
    layout="wide",
)

st.title("🩺 Cloud Diagnostics")
st.markdown(
    "_Read-only operational metadata for Cloud Gate C evidence collection. "
    "This surface is allowlisted — it never contains secrets, uploaded data, "
    "forecast values, or filesystem paths._"
)


def _deployment_url() -> str:
    """Best-effort public URL of this app (never a header dump)."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        if ctx is not None and getattr(ctx, "uri", None):
            return str(ctx.uri)
    except Exception:
        pass
    return ""


def _safe_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, indent=2, allow_nan=False)


def _diagnostics_from_dict(diag: dict):
    """Rebuild a typed CloudRuntimeDiagnostics from its exported dict."""
    from src.cloud_diagnostics import CloudRuntimeDiagnostics
    return CloudRuntimeDiagnostics(**diag)


# ---------------------------------------------------------------------------
# Optional expected collection commit (e.g. ?expected_commit=<40-hex>).
# Invalid values are ignored with a warning — never used as configuration.
# ---------------------------------------------------------------------------
expected_commit = ""
raw_expected = st.query_params.get("expected_commit", "")
if raw_expected:
    raw_expected = str(raw_expected)
    if is_exact_commit_sha(raw_expected):
        expected_commit = raw_expected
    else:
        st.warning(
            "Ignoring invalid `expected_commit` query parameter — it must be "
            "exactly 40 lowercase hexadecimal characters."
        )

backend = get_forecast_backend()
coordinator = get_coordinator()
store = get_telemetry_store()

# Per-browser collection session ID (review finding P1-5): the collection
# window is scoped to THIS browser session via st.session_state, so one
# visitor's "Begin new collection session" can never reset or split another
# visitor's evidence window.  The process-wide store is shared and bounded,
# but records are tagged with the browser session ID.
def _browser_collection_session_id() -> str:
    import uuid as _uuid
    session_id = st.session_state.get("collection_session_id", "")
    if not session_id:
        session_id = f"session_{_uuid.uuid4().hex[:12]}"
        st.session_state["collection_session_id"] = session_id
    return session_id


collection_session_id = _browser_collection_session_id()

try:
    export = build_public_diagnostics_export(
        expected_commit,
        adapter=backend,
        coordinator=coordinator,
        store=store,
        session_id=collection_session_id,
    )
    diag = export.get("diagnostics")
except Exception as exc:  # pragma: no cover - defensive
    st.error(f"Diagnostics could not be built: {exc}")
    export = None
    diag = None


def _record_event(test_name: str, passed: bool = True, details: str = "") -> None:
    """Record a canonical acceptance-test event for this browser session,
    deduplicated so repeated renders do not flood the bounded log."""
    existing = {e["test_name"] for e in store.acceptance_events(session_id=collection_session_id)}
    if test_name in existing:
        return
    try:
        store.record_acceptance_event(
            test_name, passed, details=details, session_id=collection_session_id,
        )
    except ValueError:  # pragma: no cover - defensive
        pass


if diag is not None:
    # Environment-level acceptance tests genuinely measured by the
    # dependency diagnostics (cached once per process).
    pkg = diag.get("package_versions", {})
    mandatory_known = all(
        pkg.get(name) not in ("", "unknown")
        for name in ("chronos-forecasting", "torch", "streamlit", "pandas", "numpy")
    )
    if mandatory_known:
        _record_event("dependency_install")
    if diag.get("pip_check_passed"):
        _record_event("pip_check")
    if diag.get("torch_cpu_only"):
        _record_event("cpu_only_torch")
    if not diag.get("nvidia_packages"):
        _record_event("no_nvidia_packages")

if diag is not None:
    # ------------------------------------------------------------------
    # Deployment identity (WP3): exact commit + resolution source.
    # ------------------------------------------------------------------
    st.subheader("Deployment identity")
    deployed = diag.get("deployed_commit", "")
    source = diag.get("commit_resolution_source", "")
    if deployed and source in ("explicit_verified_override", "git_head", "platform_commit_metadata"):
        st.success(
            f"Deployed commit: `{deployed}`  "
            f"(resolution source: `{source}`)"
        )
    else:
        st.warning(
            f"Deployed commit: `{deployed or 'not proven'}` — release "
            "evidence requires an exact 40-character SHA and a recorded "
            "resolution source."
        )
    if expected_commit:
        match = diag.get("expected_commit_match")
        if match is True:
            st.success(f"Expected collection commit `{expected_commit}` — **MATCH**")
        else:
            st.error(
                f"Expected collection commit `{expected_commit}` — **MISMATCH**. "
                "Refusing to collect release evidence against a different deployment."
            )
    token_state = diag.get("hf_token_present", False)
    st.markdown(
        f"Token state: `hf_token_present: {'true' if token_state else 'false'}`"
    )

    # ------------------------------------------------------------------
    # Runtime environment (WP1): allowlisted fields only.
    # ------------------------------------------------------------------
    st.subheader("Runtime environment")
    st.markdown(
        "| Attribute | Value |\n"
        "|---|---|\n"
        f"| Diagnostics ID | `{diag.get('diagnostics_id', '')}` |\n"
        f"| Generated (UTC) | `{diag.get('generated_at_utc', '')}` |\n"
        f"| Model | `{diag.get('model_id', '')}` |\n"
        f"| Pinned revision | `{diag.get('configured_revision', '')}` |\n"
        f"| Python | `{diag.get('python_version', '')}` |\n"
        f"| OS | `{diag.get('os_name', '')}` |\n"
        f"| CPU model | `{diag.get('cpu_model', '')}` |\n"
        f"| CPU logical cores | `{diag.get('cpu_logical_cores', 0)}` |\n"
        f"| RAM total (GB) | `{diag.get('ram_total_gb', 0.0)}` |\n"
        f"| Current RSS (MB) | `{diag.get('current_rss_mb', 0.0)}` |\n"
        f"| Process peak RSS (MB) | `{diag.get('process_peak_rss_mb', 0.0)}` |\n"
        f"| Pipeline constructed | `{diag.get('pipeline_constructed', False)}` |\n"
        f"| Pipeline construction count | `{diag.get('pipeline_construction_count', 0)}` |\n"
        f"| Coordinator | `{diag.get('coordinator_state', '')}` |\n"
    )

    pkg = diag.get("package_versions", {})
    pkg_rows = "".join(
        f"| `{name}` | `{pkg.get(name, 'unknown')}` |\n"
        for name in ("chronos-forecasting", "torch", "streamlit", "pandas", "numpy", "python")
    )
    st.markdown("**Package versions**\n\n| Package | Version |\n|---|---|\n" + pkg_rows)

    # ------------------------------------------------------------------
    # Dependency diagnostics (WP6): measured, not inferred.
    # ------------------------------------------------------------------
    st.subheader("Dependency diagnostics")
    st.markdown(
        "| Check | Result |\n"
        "|---|---|\n"
        f"| `pip check` | {'passed' if diag.get('pip_check_passed') else 'FAILED'} |\n"
        f"| CPU-only Torch | {'yes' if diag.get('torch_cpu_only') else 'no'} |\n"
        f"| torch.version.cuda | `{diag.get('torch_cuda_version') or 'None'}` |\n"
        f"| NVIDIA packages | `{', '.join(diag.get('nvidia_packages', [])) or 'none'}` |\n"
    )
    if diag.get("pip_check_summary"):
        st.caption(f"pip check summary: {diag.get('pip_check_summary')}")

    # ------------------------------------------------------------------
    # Request telemetry (WP4/WP5): bounded, typed records.
    # ------------------------------------------------------------------
    st.subheader("Request telemetry")
    records = export.get("request_records", [])
    st.markdown(
        f"{export.get('request_count', len(records))} typed request record(s) "
        f"retained for collection session `{collection_session_id}` (bounded at "
        f"{store.max_records})."
    )
    if records:
        st.dataframe(
            [
                {
                    "request_id": r.get("request_id", ""),
                    "started_at_utc": r.get("started_at_utc", ""),
                    "completed_at_utc": r.get("completed_at_utc", ""),
                    "success": r.get("success", False),
                    "queue_s": r.get("queue_seconds", 0.0),
                    "inference_s": r.get("inference_seconds", 0.0),
                    "pipeline_constructed": r.get("pipeline_constructed", False),
                    "pipeline_reused": r.get("pipeline_reused", False),
                    "error_category": r.get("error_category", ""),
                }
                for r in records
            ],
            use_container_width=True,
        )

    # ------------------------------------------------------------------
    # Safe JSON export (WP2): deterministic, allowlisted, canonical digest.
    # ------------------------------------------------------------------
    st.subheader("Safe JSON export")
    st.warning(
        "This export contains operational metadata. It contains no secrets, "
        "no uploaded data, and no forecast values."
    )
    export_payload = {
        k: v for k, v in export.items() if k != "canonical_digest"
    }
    json_text = _safe_json(export_payload)
    st.download_button(
        "Download diagnostics JSON",
        data=json_text,
        file_name="cloud_diagnostics.json",
        mime="application/json",
    )
    digest = export.get("canonical_digest", "")
    st.code(f"SHA-256 (canonical): {digest}")
    st.caption(
        "The canonical digest covers the exact exported payload. Any "
        "alteration changes the digest."
    )
    if not export.get("release_ready", False):
        st.warning(
            "This snapshot is NOT release-ready: "
            + "; ".join(export.get("validation_errors", []) or ["unknown errors"])
        )

# ---------------------------------------------------------------------------
# Collection session controls (WP11): deliberate UI actions, no secret input.
# ---------------------------------------------------------------------------
st.subheader("Collection session")
st.caption(
    "**Begin** starts a fresh collection window for **this browser session** "
    "(new session ID; other visitors' windows are untouched). **Finalise** "
    "binds the session record — every request ID recorded in this window, "
    "the acceptance tests that actually ran, the runtime-diagnostics digest, "
    "and the deployment identity — to a canonical digest receipt. No secret "
    "input is required."
)

if st.button("Begin new collection session"):
    import uuid as _uuid
    new_id = f"session_{_uuid.uuid4().hex[:12]}"
    # Per-browser only: never clears the process-wide store or another
    # visitor's session window (review finding P1-5).
    st.session_state["collection_session_id"] = new_id
    st.session_state["collection_started_at_utc"] = datetime.now(timezone.utc).isoformat()
    st.success(f"New collection session started: `{new_id}`")

if st.button("Finalise collection session"):
    try:
        if diag is None:
            st.error("Cannot finalise: diagnostics snapshot unavailable.")
        else:
            deployment_url = _deployment_url()
            started_at = st.session_state.get("collection_started_at_utc", "")
            # Concurrency is a process-level phenomenon: use the protected
            # shared cohort (all requests in this collection window,
            # including peer-session requests) so the overlap categoriser
            # sees both participants of a genuine two-session run
            # (codex P1-7).  Public resets cannot alter this cohort — only
            # the deliberate Begin action defines the window.
            cohort = store.snapshot()
            window_start = started_at or diag.get("generated_at_utc", "")
            if window_start:
                cohort = [
                    r for r in cohort
                    if (r.get("started_at_utc") or r.get("inference_started_at_utc") or "") >= window_start
                ]
            from src.cloud_diagnostics import any_overlapping_pair
            if any_overlapping_pair(cohort):
                _record_event("two_session_concurrency")
            # Only acceptance tests that genuinely ran are recorded
            # (codex P1-4/P1-6), deduplicated so repeated warm runs do not
            # produce duplicate names (codex P1-9).
            ran_events = store.acceptance_events(session_id=collection_session_id)
            test_names = list(dict.fromkeys(
                e["test_name"] for e in ran_events if e.get("passed")
            ))
            session_record = build_collection_session_record(
                session_id=collection_session_id,
                deployed_commit=diag.get("deployed_commit", ""),
                commit_resolution_source=diag.get("commit_resolution_source", ""),
                deployment_url=deployment_url,
                diagnostics=_diagnostics_from_dict(diag),
                acceptance_test_names=test_names,
                request_records=cohort,
                started_at_utc=started_at or diag.get("generated_at_utc", ""),
                completed_at_utc=datetime.now(timezone.utc).isoformat(),
            )
            session_errors = session_record.validate()
            if session_errors:
                st.warning("Session record validation issues: " + "; ".join(session_errors))
            receipt = build_collection_receipt(session_record)
            st.download_button(
                "Download collection session record",
                data=_safe_json(session_record.to_dict()),
                file_name="cloud_collection_session.json",
                mime="application/json",
            )
            st.download_button(
                "Download collection receipt",
                data=_safe_json(receipt),
                file_name="cloud_collection_receipt.json",
                mime="application/json",
            )
            st.code(f"Receipt canonical content SHA-256: {receipt.get('canonical_content_sha256', '')}")
            if not deployment_url:
                st.caption(
                    "Deployment URL could not be detected from the public "
                    "request; the collector will supply the public app URL "
                    "when building release evidence."
                )
    except Exception as exc:  # pragma: no cover - defensive
        st.error(f"Could not finalise collection session: {exc}")
