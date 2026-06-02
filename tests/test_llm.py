"""
LLM integration tests — plan 02-02 Wave 2.
LLM-01..08 requirements. Uses respx for httpx mocking.
D2 FOOT-GUN pinned by test_d2_fallback_is_dropped.
"""

import asyncio
import json

import httpx
import respx

from src.artiscrapper.llm import LLMVerdict, classify_candidate, should_keep

# ──────────────────────────────────────────
# LLM-02: LLMVerdict model validation
# ──────────────────────────────────────────


async def test_verdict_valid():
    """LLM-02: LLMVerdict.model_validate_json() accepts valid JSON verdict."""
    verdict_json = json.dumps(
        {
            "is_product": True,
            "confidence": 0.95,
            "price_hint": 8500.0,
            "store_hint": "Tiendanube",
            "freshness_signal": "static_catalog",
            "reason": "JSON-LD product con precio",
        }
    )
    v = LLMVerdict.model_validate_json(verdict_json)
    assert v.is_product is True
    assert v.confidence == 0.95
    assert v.freshness_signal == "static_catalog"
    assert v.price_hint == 8500.0
    assert v.store_hint == "Tiendanube"


def test_fallback_shape():
    """LLM-02: LLMVerdict.fallback() returns confidence=0.3, is_product=True."""
    v = LLMVerdict.fallback("timeout")
    assert v.confidence == 0.3
    assert v.is_product is True
    assert v.freshness_signal == "unknown"
    assert v.reason == "llm_fail:timeout"


# ──────────────────────────────────────────
# D2 pin: fallback IS dropped
# ──────────────────────────────────────────


def test_d2_fallback_is_dropped():
    """D2: timeout fallback confidence=0.3 IS dropped at <0.4 cut. This is the critical invariant."""
    v = LLMVerdict.fallback("timeout")
    assert v.confidence == 0.3
    assert not should_keep(v), "D2 foot-gun: fallback verdict must be dropped by should_keep()!"


def test_should_keep_drops_blog():
    """LLM-05: blog freshness_signal → dropped regardless of confidence."""
    v = LLMVerdict(
        is_product=True,
        confidence=0.9,
        freshness_signal="blog",
        reason="Blog sobre repuestos",
    )
    assert not should_keep(v)


def test_should_keep_passes_valid():
    """LLM-05: high-confidence product with live_marketplace → kept."""
    v = LLMVerdict(
        is_product=True,
        confidence=0.95,
        freshness_signal="live_marketplace",
        reason="MELI card con precio",
    )
    assert should_keep(v)


def test_should_keep_drops_non_product():
    """LLM-05: is_product=False → dropped regardless of confidence."""
    v = LLMVerdict(
        is_product=False,
        confidence=0.97,
        freshness_signal="blog",
        reason="Tutorial, no producto",
    )
    assert not should_keep(v)


# ──────────────────────────────────────────
# LLM-01/07: Router call shape (respx mock)
# ──────────────────────────────────────────


async def test_router_call_shape():
    """LLM-01/07: LLM router uses OpenAI-compat (choices[0].message.content)."""
    verdict_json = json.dumps(
        {
            "is_product": True,
            "confidence": 0.95,
            "price_hint": 8500.0,
            "store_hint": "Tiendanube",
            "freshness_signal": "static_catalog",
            "reason": "JSON-LD product",
        }
    )
    with respx.mock:
        respx.post("http://127.0.0.1:3210/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={"choices": [{"message": {"content": verdict_json}, "finish_reason": "stop"}]},
            )
        )
        sem = asyncio.Semaphore(4)
        async with httpx.AsyncClient(http2=True) as client:
            verdict = await classify_candidate(
                client,
                {"url": "https://tienda.com/prod", "title": "Filtro", "snippet": "En stock"},
                sem,
                "http://127.0.0.1:3210",
                "test-token",
            )
        assert verdict.confidence == 0.95
        assert verdict.is_product is True
        assert verdict.freshness_signal == "static_catalog"


async def test_router_timeout_returns_fallback():
    """LLM-04: 5s timeout → fallback verdict with reason='llm_fail:timeout'."""
    with respx.mock:
        respx.post("http://127.0.0.1:3210/v1/chat/completions").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        sem = asyncio.Semaphore(4)
        async with httpx.AsyncClient(http2=True) as client:
            verdict = await classify_candidate(
                client,
                {"url": "https://tienda.com/prod", "title": "Filtro", "snippet": "En stock"},
                sem,
                "http://127.0.0.1:3210",
                "test-token",
            )
        # Fallback from timeout
        assert verdict.confidence == 0.3
        assert verdict.reason == "llm_fail:timeout"
        # D2: timeout fallback is dropped
        assert not should_keep(verdict)


# ──────────────────────────────────────────
# LLM-03: Semaphore concurrency
# ──────────────────────────────────────────


async def test_concurrency_semaphore():
    """LLM-03: Semaphore(4) limits concurrent LLM calls — all 8 complete without error."""
    verdict_json = json.dumps(
        {
            "is_product": True,
            "confidence": 0.8,
            "price_hint": None,
            "store_hint": None,
            "freshness_signal": "static_catalog",
            "reason": "test",
        }
    )
    with respx.mock:
        respx.post("http://127.0.0.1:3210/v1/chat/completions").mock(
            return_value=httpx.Response(
                200, json={"choices": [{"message": {"content": verdict_json}}]}
            )
        )
        sem = asyncio.Semaphore(4)
        candidates = [
            {"url": f"https://tienda.com/prod/{i}", "title": f"Prod {i}", "snippet": "En stock"}
            for i in range(8)
        ]
        async with httpx.AsyncClient(http2=True) as client:
            verdicts = await asyncio.gather(
                *[
                    classify_candidate(client, c, sem, "http://127.0.0.1:3210", "test-token")
                    for c in candidates
                ]
            )
        assert len(verdicts) == 8
        # All should be valid LLMVerdict objects (no exceptions)
        for v in verdicts:
            assert isinstance(v, LLMVerdict)
            assert v.confidence == 0.8
