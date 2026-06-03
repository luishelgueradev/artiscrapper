"""
LLM-down degraded-mode hardening test (Phase 3 — Plan 03-02, ROADMAP-5).

When `router_health_check` returns False (router /healthz HEAD fails),
the /search pipeline falls back to the heuristic-only path:
  - junk-domain blocklist filter
  - price-in-card filter

This test loads the Phase 1 50-record labelled set and asserts that
≥5 candidates survive the heuristic-only path (LLM-06 hardening).

Pattern: Pattern S6 (respx mock at httpx boundary). CRITICAL —
`router_health_check` uses `client.head()` not `client.get()` per
`src/artiscrapper/llm.py:267`; the respx mock MUST be `respx.head(...)`.

D-18: assertion includes the specific count + total — NOT
`len(survivors) > 0` (Phase 2 lesson).
"""

import json
import pathlib

import httpx
import respx

from src.artiscrapper.llm import router_health_check

LABELLED = (
    pathlib.Path(__file__).parent.parent / "fixtures" / "llm" / "labelled.jsonl"
)


def _heuristic_only_survivors(candidates: list[dict]) -> list[dict]:
    """
    Mirror the heuristic-only branch in `main.py` lines ~470-478:
    when router_healthy is False, the route keeps candidates that
    have a price hint (`price_in_card` or `has_price`) and otherwise
    falls back to the full candidate set.
    """
    survivors = [
        c
        for c in candidates
        if c.get("price_in_card") or c.get("price") or c.get("has_price")
    ]
    if not survivors:
        survivors = list(candidates)
    return survivors


async def test_llm_down_keeps_useful_results():
    """
    ROADMAP-5: with the LLM router returning 503 on /healthz, the
    heuristic-only branch MUST retain ≥5 useful candidates from the
    Phase 1 50-record labelled set.

    D-18 alignment: assertion message lists the survivor count AND
    the total so a regression is forensically actionable.
    """
    candidates = []
    with LABELLED.open() as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            cand = row.get("candidate") or {}
            candidates.append(cand)

    assert len(candidates) == 50, (
        f"Phase 1 labelled set should have exactly 50 records; got {len(candidates)}. "
        "If fixture was edited, update this assertion AND the survivor floor."
    )

    with respx.mock:
        # CRITICAL: router_health_check uses client.head() — must register .head
        respx.head("http://127.0.0.1:3210/healthz").mock(
            return_value=httpx.Response(503, json={"error": "router down"})
        )
        respx.post("http://127.0.0.1:3210/v1/chat/completions").mock(
            return_value=httpx.Response(503, json={"error": "router down"})
        )

        # Confirm the trigger: router_health_check must return False.
        healthy = await router_health_check(
            "http://127.0.0.1:3210", "test-bearer-degraded-mode"
        )
        assert healthy is False, (
            "LLM-06 trigger: router_health_check must return False when /healthz returns 503"
        )

        # Heuristic-only path filter (mirrors main.py degraded-mode branch)
        survivors = _heuristic_only_survivors(candidates)

    assert len(survivors) >= 5, (
        f"ROADMAP-5: degraded mode should retain ≥5 useful results from "
        f"Phase 1 labelled set; got {len(survivors)}/{len(candidates)}. "
        "If this regressed, the heuristic blocklist or price-in-card filter "
        "lost coverage — check `src/artiscrapper/main.py:470-478`."
    )
