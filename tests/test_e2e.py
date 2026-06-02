"""
End-to-end tests against live dev-box. Skipped by default.
Marked @pytest.mark.e2e — only run with: pytest -m e2e
"""
import pytest


@pytest.mark.e2e
@pytest.mark.skip(reason="e2e: needs live dev-box with Cloak + LLM router running")
async def test_serp_pelota():
    """
    NF-01 E2E: POST /search {query: 'pelota playera quico'} → ≥10 results, ≥6 with price.
    Zero blogs/wiki/youtube in top 10 results (PRD §10).
    """
    import httpx
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        resp = await client.post("/search", json={"query": "pelota playera quico"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 10
        with_price = sum(1 for r in data["results"] if r.get("price"))
        assert with_price >= 6
        for r in data["results"][:10]:
            url = r.get("url", "")
            assert "youtube.com" not in url
            assert "wikipedia.org" not in url
            assert "reddit.com" not in url


@pytest.mark.e2e
@pytest.mark.skip(reason="e2e: needs live dev-box with Cloak + LLM router running")
async def test_cache_hit():
    """
    NF-01 E2E: Identical query within 24h → cache_hit=true, response < 500ms.
    """
    import httpx
    import time
    query = "filtro aceite ford focus"
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        # First request (may be cold)
        await client.post("/search", json={"query": query})
        # Second request should be cached
        t0 = time.monotonic()
        resp = await client.post("/search", json={"query": query})
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["cache_hit"] is True
        assert elapsed_ms < 500, f"Cache hit took {elapsed_ms:.0f}ms (expected <500ms)"
