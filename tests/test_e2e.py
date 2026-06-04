"""
End-to-end tests against live dev-box at localhost:8000.
Skipped by default — activate with: E2E=1 pytest tests/test_e2e.py -x -q -m e2e

PRD §10 success criteria tested here:
  - POST /search q="pelota playera quico" → ≥10 results, ≥6 with price, zero blogs in top 10
  - Identical query within session → cache_hit=True, elapsed <500ms
"""

import os
import time
from urllib.parse import urlparse

import httpx
import pytest

_E2E_ACTIVE = os.getenv("E2E", "0") == "1"

# Base URL of the live dev-box service
_BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000")

# Junk hostnames to block from top-10 results (PRD §10 acceptance criterion)
_JUNK_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "wikipedia.org",
        "es.wikipedia.org",
        "reddit.com",
        "www.reddit.com",
        "fandom.com",
        "quora.com",
    }
)


@pytest.mark.e2e
@pytest.mark.skipif(not _E2E_ACTIVE, reason="set E2E=1 to run live tests (requires localhost:8000)")
def test_serp_pelota():
    """
    NF-01 E2E: POST /search {query: 'pelota playera quico'} → ≥10 results, ≥6 with price.
    Zero blogs/wiki/youtube in top 10 results (PRD §10).
    pelota playera quico = beach ball (Spanish AR query for e-commerce auto-parts shop context)
    """
    with httpx.Client(base_url=_BASE_URL, timeout=60.0) as client:
        resp = client.post(
            "/search",
            json={"query": "pelota playera quico"},
            headers={"X-API-Key": os.getenv("E2E_API_KEY", "test-key-1")},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"

    data = resp.json()
    results = data.get("results", [])

    # PRD §10 criterion 1: at least 10 results
    assert len(results) >= 10, f"Expected ≥10 results, got {len(results)}"

    # PRD §10 criterion 2: at least 6 with price non-null
    with_price = sum(1 for r in results if r.get("price") is not None)
    assert with_price >= 6, f"Expected ≥6 results with price, got {with_price}"

    # PRD §10 criterion 3: zero junk domains in top 10
    for r in results[:10]:
        url = r.get("url", "")
        host = urlparse(url).netloc.lower()
        # Strip www. prefix for comparison
        bare_host = host.removeprefix("www.")
        assert host not in _JUNK_HOSTS and bare_host not in _JUNK_HOSTS, (
            f"Junk domain in top-10: {host} (url={url})"
        )

    # Cache hit should be False on first call
    meta = data.get("metadata", {})
    assert meta.get("cache_hit") is False, (
        f"Expected cache_hit=False on first call, got: {meta.get('cache_hit')}"
    )


@pytest.mark.e2e
@pytest.mark.skipif(not _E2E_ACTIVE, reason="set E2E=1 to run live tests (requires localhost:8000)")
def test_cache_hit():
    """
    NF-01 E2E: Identical query within 24h → cache_hit=True, response <500ms (CACHE-05).
    Runs AFTER test_serp_pelota has populated the cache for the same query.
    """
    query = "pelota playera quico"
    with httpx.Client(base_url=_BASE_URL, timeout=60.0) as client:
        # Ensure the cache is populated (may already be from test_serp_pelota)
        client.post(
            "/search",
            json={"query": query},
            headers={"X-API-Key": os.getenv("E2E_API_KEY", "test-key-1")},
        )

        # Second call should be a cache hit
        t0 = time.monotonic()
        resp = client.post(
            "/search",
            json={"query": query},
            headers={"X-API-Key": os.getenv("E2E_API_KEY", "test-key-1")},
        )
        elapsed_ms = (time.monotonic() - t0) * 1000

    assert resp.status_code == 200
    data = resp.json()
    meta = data.get("metadata", {})

    assert meta.get("cache_hit") is True, (
        f"Expected cache_hit=True on second call, got: {meta.get('cache_hit')}"
    )
    assert elapsed_ms < 500, f"Cache hit response took {elapsed_ms:.0f}ms, expected <500ms (NF-01)"
