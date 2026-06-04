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
    be mounted via prometheus_client.make_asgi_app() so per-route mechanisms
    (slowapi limits, verify_api_key Depends) do NOT apply. WR-06 correction:
    this mount does NOT bypass app.add_middleware — Starlette installs
    middleware at the ASGI level so CorrelationIdMiddleware wraps /metrics
    too. The invariant tracked here is that /metrics has no slowapi /
    verify_api_key wrapping, NOT that "all middleware is bypassed".
"""

import os
import subprocess
import sys

# WR-03 (Phase 3.1): test_recycle_triggers re-introduces
# `from src.artiscrapper.config import settings`, which requires
# LLM_ROUTER_BEARER_TOKEN at first Settings() call. Pre-set a test
# value so the import doesn't fail. `setdefault` honors the cross-test
# contract (a sibling-imported test's token wins if already set).
os.environ.setdefault("LLM_ROUTER_BEARER_TOKEN", "test-token-footguns")


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

    WR-03 (Phase 3.1) fix: the previous version of this test rebound
    `BROWSER_RECYCLE_AFTER = 200` as a local int and then asserted
    `X >= X` against itself — a tautology that matched any value and
    would silently pass even if the default drifted. This rewrite pins
    `settings.BROWSER_RECYCLE_AFTER` against the source of truth
    (config.py default) AND the upper cap (500 per Phase 1 SPIKE
    memory-drift cliff documented in SPIKE.md §Browser / Playwright
    issue #15400).
    """
    from src.artiscrapper.config import settings

    # WR-03 fix: pin the DEFAULT against the source of truth + the cap.
    # If a future change bumps settings.BROWSER_RECYCLE_AFTER past 500 (the
    # recycle-too-late cliff documented in Phase 1 SPIKE), this test fails.
    assert settings.BROWSER_RECYCLE_AFTER == 200, (
        f"WR-03: BROWSER_RECYCLE_AFTER drifted from documented default 200; "
        f"got {settings.BROWSER_RECYCLE_AFTER}. Update test + SPIKE.md if intentional."
    )
    assert settings.BROWSER_RECYCLE_AFTER <= 500, (
        "BROWSER-03: recycle threshold above 500 risks Chromium memory drift "
        "(Phase 1 SPIKE.md §Browser; Playwright issue #15400)"
    )

    # Pin the actual recycle condition's boundary semantics.
    uses_over_threshold = settings.BROWSER_RECYCLE_AFTER + 1
    assert uses_over_threshold >= settings.BROWSER_RECYCLE_AFTER, (
        f"BROWSER-03: uses={uses_over_threshold} should trigger recycle "
        f"(BROWSER_RECYCLE_AFTER={settings.BROWSER_RECYCLE_AFTER})"
    )

    # Below-threshold case (regression pin):
    uses_below_threshold = settings.BROWSER_RECYCLE_AFTER - 1
    assert uses_below_threshold < settings.BROWSER_RECYCLE_AFTER, (
        f"BROWSER-03: uses={uses_below_threshold} should NOT trigger recycle"
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


def test_metrics_endpoint_unprotected_by_design():
    """
    D-10: /metrics must be mounted via prometheus_client.make_asgi_app() so
    per-route mechanisms (slowapi limits, verify_api_key Depends) do NOT
    apply. WR-06 correction: app.add_middleware DOES wrap the ASGI sub-app
    (Starlette installs middleware at the ASGI level), so the invariant we
    assert here is "no per-route wrapping", not "no middleware at all".
    """
    result = subprocess.run(
        ["grep", "-n", "/metrics", "src/artiscrapper/main.py"],
        capture_output=True,
        text=True,
    )
    assert "make_asgi_app()" in result.stdout, (
        "D-10: /metrics must be mounted via prometheus_client.make_asgi_app() "
        "(ASGI sub-app), NOT a FastAPI route — otherwise slowapi + "
        "verify_api_key would silently wrap it. main.py grep output:\n"
        + result.stdout
    )
