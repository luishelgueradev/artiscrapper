"""Phase 0.2.2 HARNESS-03 — sample hot-path overhead + safety tests."""
import asyncio
import time
from pathlib import Path

import pytest

from src.artiscrapper.main import _parity_audit_sample

FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "serp" / "pla_unit_robotech.html"
)


@pytest.mark.asyncio
async def test_sample_p99_under_50ms_on_fixture():
    """Run _parity_audit_sample 30 times on the robotech fixture; p99 must be <50ms.

    Why 50ms: this is the budget for not noticeably impacting /search p99
    even when sampling at 100% (worst case). At default
    PARITY_SAMPLE_RATE=0.1, the real impact on average /search latency
    is /10 of the per-sample cost.
    """
    html = FIXTURE.read_text()
    # Warm-up (first call pays import + lazy compile costs).
    await _parity_audit_sample("warmup query", html)

    timings_ms: list[float] = []
    for _ in range(30):
        t0 = time.perf_counter()
        await _parity_audit_sample("benchmark query", html)
        timings_ms.append((time.perf_counter() - t0) * 1000)

    timings_ms.sort()
    # With n=30, "p99" is approximated by the max measurement.
    p99 = timings_ms[-1]
    median = timings_ms[len(timings_ms) // 2]
    print(
        f"\nparity sample on {len(html) // 1024}KB fixture: "
        f"median={median:.1f}ms p99(~max)={p99:.1f}ms"
    )
    assert p99 < 50.0, f"sample overhead too high: p99={p99:.1f}ms (>=50ms)"


@pytest.mark.asyncio
async def test_sample_never_raises_on_broken_html():
    """Even truly broken inputs must NOT raise — failure is logged silently."""
    for bad in ["", "<<<not html>>>", "{}", " ", "\x00\x01"]:
        # If this raises, the test fails. If it returns None, success.
        await _parity_audit_sample("safety query", bad)


@pytest.mark.asyncio
async def test_sample_updates_metrics_on_real_fixture():
    """A successful sample call updates the parity gauges with non-zero values."""
    from src.artiscrapper.metrics import (
        parity_pla_extracted,
        parity_pla_in_html,
    )
    html = FIXTURE.read_text()
    label = "metric update query"
    await _parity_audit_sample(label, html)

    pla_in_html_val = parity_pla_in_html.labels(query=label)._value.get()
    extracted_val = parity_pla_extracted.labels(query=label)._value.get()
    assert pla_in_html_val >= 4, (
        f"Expected >=4 pla in frozen fixture, got {pla_in_html_val}"
    )
    assert extracted_val >= 4
