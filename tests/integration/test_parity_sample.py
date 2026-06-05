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
async def test_sample_median_under_50ms_on_fixture():
    """Run _parity_audit_sample 30 times on the robotech fixture; median <50ms.

    Two thresholds:
      - median < 50ms        — typical-case budget: the sample doesn't
                               noticeably impact /search p50 even at
                               sample_rate=1.0. At default 0.1, real average
                               cost is /10 of this.
      - max     < 350ms      — safety cap against GC/page-cache spikes. With
                               n=30, "p99" approximated by max is dominated
                               by environmental noise; we still want a hard
                               ceiling so a true pathological case (e.g.
                               selectolax crash, infinite loop) trips the
                               test. parse_serp() on a 720KB SERP profiles
                               at median 17ms / occasional spikes up to
                               300ms under cold cache (see commit message
                               for profile data).
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
    median = timings_ms[len(timings_ms) // 2]
    p90 = timings_ms[int(len(timings_ms) * 0.90)]
    max_ms = timings_ms[-1]
    print(
        f"\nparity sample on {len(html) // 1024}KB fixture: "
        f"median={median:.1f}ms p90={p90:.1f}ms max={max_ms:.1f}ms"
    )
    assert median < 50.0, f"sample median budget breached: {median:.1f}ms (>=50ms)"
    assert max_ms < 350.0, f"sample max safety cap breached: {max_ms:.1f}ms (>=350ms)"


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
