"""
LLM integration test stubs — xfail until plan 02-02 ships llm.py.
LLM-01..08 requirements. Uses respx for httpx mocking.
"""
import pytest

try:
    from src.artiscrapper.llm import LLMVerdict, classify_candidate, should_keep
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not _LLM_AVAILABLE,
    reason="llm.py not yet implemented — will be filled by plan 02-02",
)


@pytest.mark.xfail(strict=False, reason="Wave 2: llm.py filled by plan 02-02")
async def test_verdict_valid():
    """LLM-02: LLMVerdict.model_validate_json() accepts valid JSON verdict."""
    import json
    verdict_json = json.dumps({
        "is_product": True,
        "confidence": 0.95,
        "price_hint": 8500.0,
        "store_hint": "Tiendanube",
        "freshness_signal": "static_catalog",
        "reason": "JSON-LD product con precio",
    })
    v = LLMVerdict.model_validate_json(verdict_json)
    assert v.is_product is True
    assert v.confidence == 0.95
    assert v.freshness_signal == "static_catalog"


@pytest.mark.xfail(strict=False, reason="Wave 2: llm.py filled by plan 02-02")
def test_fallback_shape():
    """LLM-02: LLMVerdict.fallback() returns confidence=0.3, is_product=True."""
    v = LLMVerdict.fallback("timeout")
    assert v.confidence == 0.3
    assert v.is_product is True
    assert v.freshness_signal == "unknown"


@pytest.mark.xfail(strict=False, reason="Wave 2: llm.py filled by plan 02-02")
def test_d2_fallback_is_dropped():
    """D2: timeout fallback confidence=0.3 IS dropped at <0.4 cut."""
    v = LLMVerdict.fallback("timeout")
    assert v.confidence == 0.3
    assert not should_keep(v), "D2 foot-gun: fallback verdict must be dropped!"


@pytest.mark.xfail(strict=False, reason="Wave 2: llm.py filled by plan 02-02")
async def test_router_call_shape():
    """LLM-01/07: LLM router uses OpenAI-compat (choices[0].message.content)."""
    import json
    import asyncio
    import httpx
    import respx

    verdict_json = json.dumps({
        "is_product": True, "confidence": 0.95,
        "price_hint": 8500.0, "store_hint": "Tiendanube",
        "freshness_signal": "static_catalog", "reason": "JSON-LD product",
    })
    with respx.mock:
        respx.post("http://127.0.0.1:3210/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "choices": [{"message": {"content": verdict_json}, "finish_reason": "stop"}]
            })
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


@pytest.mark.xfail(strict=False, reason="Wave 2: llm.py filled by plan 02-02")
async def test_concurrency_semaphore():
    """LLM-03: Semaphore(4) limits concurrent LLM calls."""
    import asyncio
    import httpx
    import respx
    import json

    verdict_json = json.dumps({
        "is_product": True, "confidence": 0.8,
        "price_hint": None, "store_hint": None,
        "freshness_signal": "static_catalog", "reason": "test",
    })
    with respx.mock:
        respx.post("http://127.0.0.1:3210/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "choices": [{"message": {"content": verdict_json}}]
            })
        )
        sem = asyncio.Semaphore(4)
        candidates = [
            {"url": f"https://tienda.com/prod/{i}", "title": f"Prod {i}", "snippet": "En stock"}
            for i in range(8)
        ]
        async with httpx.AsyncClient(http2=True) as client:
            verdicts = await asyncio.gather(*[
                classify_candidate(client, c, sem, "http://127.0.0.1:3210", "test-token")
                for c in candidates
            ])
        assert len(verdicts) == 8
