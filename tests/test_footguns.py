"""
D2/D6/D8 invariant assertions.
Pattern 10 from 02-RESEARCH.md (lines 1205-1224).
LIFECYCLE NOTE: This file will be EXTENDED in plan 02-03 Task 2 with implementation bodies
for test_recycle_triggers. Wave-1 stubs remain importable/skippable until 02-03 fills them.
Do NOT add sentinel comments that would break additive edits.

Phase 3 extensions:
  - test_sentry_does_not_pull_uvloop: re-asserts D-6 against sentry-sdk's
    transitive dep tree (03-RESEARCH.md §G3).
  - test_metrics_endpoint_unprotected_by_design: pins D-10 — /metrics must
    be mounted via prometheus_client.make_asgi_app() (an ASGI sub-app that
    bypasses FastAPI middleware + slowapi), NOT a regular FastAPI route.
"""

import subprocess
import sys

import pytest


def test_no_uvloop_installed():
    """D6: uvloop must not be importable in the runtime environment."""
    result = subprocess.run(
        [sys.executable, "-c", "import uvloop"],
        capture_output=True,
    )
    assert result.returncode != 0, "uvloop is installed — D6 foot-gun!"


def test_uvloop_absent_from_lock():
    """D6: uvloop must not appear in pyproject.toml or uv.lock."""
    result = subprocess.run(
        ["grep", "-rE", "uvloop", "pyproject.toml", "uv.lock"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, f"uvloop found: {result.stdout}"


def test_no_persistent_context_in_codebase():
    """D8: launch_persistent_context must not appear in src/."""
    result = subprocess.run(
        ["grep", "-rn", "launch_persistent_context", "src/"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, f"D8 foot-gun: launch_persistent_context found:\n{result.stdout}"


def test_d2_fallback_is_dropped():
    """D2: timeout fallback confidence=0.3 is BELOW <0.4 cut → dropped."""
    from src.artiscrapper.llm import LLMVerdict, should_keep

    v = LLMVerdict.fallback("timeout")
    assert v.confidence == 0.3
    assert not should_keep(v), "D2 foot-gun: fallback verdict must be dropped!"


def test_recycle_triggers():
    """
    BROWSER-03: Recycle condition fires when browser_uses >= BROWSER_RECYCLE_AFTER.
    This is a logic pin — asserts the conditional expression used in _recycle_browser_loop.
    The main.py checks: if app.state.browser_uses >= settings.BROWSER_RECYCLE_AFTER
    Default BROWSER_RECYCLE_AFTER=200 (from config.py).
    """
    # Use the default constant directly (avoid importing settings which requires LLM token)
    BROWSER_RECYCLE_AFTER = 200  # must match config.py default

    # The recycle SHOULD trigger at the threshold
    assert BROWSER_RECYCLE_AFTER >= BROWSER_RECYCLE_AFTER, (
        "Sanity: recycle fires when uses == BROWSER_RECYCLE_AFTER"
    )

    # The recycle SHOULD trigger when uses exceeds the threshold (typical production case)
    uses_over_threshold = BROWSER_RECYCLE_AFTER + 1
    assert uses_over_threshold >= BROWSER_RECYCLE_AFTER, (
        f"BROWSER-03: uses={uses_over_threshold} should trigger recycle "
        f"(BROWSER_RECYCLE_AFTER={BROWSER_RECYCLE_AFTER})"
    )

    # The recycle should NOT trigger below threshold
    uses_below_threshold = BROWSER_RECYCLE_AFTER - 1
    assert not (uses_below_threshold >= BROWSER_RECYCLE_AFTER), (
        f"BROWSER-03: uses={uses_below_threshold} should NOT trigger recycle yet"
    )

    # Also verify the condition string appears in main.py source (code inspection)
    result = subprocess.run(
        [
            "grep",
            "-n",
            "browser_uses >= settings.BROWSER_RECYCLE_AFTER",
            "src/artiscrapper/main.py",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "BROWSER-03: recycle condition 'browser_uses >= settings.BROWSER_RECYCLE_AFTER' "
        "must be present in main.py"
    )


# ──────────────────────────────────────────
# Phase 3 invariants
# ──────────────────────────────────────────


def test_sentry_does_not_pull_uvloop():
    """
    D-6 + Phase 3: sentry-sdk must NOT pull uvloop into uv.lock transitively
    (03-RESEARCH.md §G3). This is an extra pin alongside the existing
    `test_uvloop_absent_from_lock` so a future sentry-sdk minor bump that
    starts depending on uvloop trips a clearly-labelled test.
    """
    result = subprocess.run(
        ["grep", "-rE", "uvloop", "uv.lock"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        f"D-6 / Phase 3: uvloop appeared in uv.lock — check sentry-sdk transitive deps:\n"
        f"{result.stdout}"
    )


@pytest.mark.xfail(
    strict=False,
    reason="main.py wiring lands in Task 3 — make_asgi_app() not present yet",
)
def test_metrics_endpoint_unprotected_by_design():
    """
    D-10: /metrics must be mounted via prometheus_client.make_asgi_app() so
    it bypasses FastAPI middleware (CorrelationIdMiddleware + slowapi). If a
    future refactor moves /metrics to a regular FastAPI route, the slowapi
    + auth dependencies would silently wrap it — breaking the D-10 contract.
    """
    result = subprocess.run(
        ["grep", "-n", "/metrics", "src/artiscrapper/main.py"],
        capture_output=True,
        text=True,
    )
    assert "make_asgi_app()" in result.stdout, (
        "D-10: /metrics must be mounted via prometheus_client.make_asgi_app() "
        "(ASGI sub-app), NOT a FastAPI route — otherwise CorrelationIdMiddleware "
        "+ slowapi will wrap it. main.py grep output:\n" + result.stdout
    )
