"""
Compara dos estrategias:

A) Per-candidate (actual): N llamadas al LLM, una por candidato. Cada una
   devuelve LLMVerdict para 1 candidato.

B) Batch: 1 llamada con TODOS los candidatos en el prompt. El LLM devuelve
   un JSON array con N veredictos. Menos network overhead, mejor KV-cache
   reuse del system prompt.

Mide latencia y mantiene calidad (precision/recall vs ground truth).
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx  # noqa: E402

from src.artiscrapper.config import settings  # noqa: E402
from src.artiscrapper.llm import (  # noqa: E402
    SYSTEM_PROMPT,
    FEW_SHOT_EXAMPLES,
    classify_candidate,
    resolve_model,
)

FIX = Path("tests/fixtures/llm/labelled.jsonl")
OUT = Path("scripts/perfaudit/04-llm-batch.json")

# Prompt user message para batch — devuelve JSON array
BATCH_USER_TEMPLATE = """Classify the following SERP candidates. Return a JSON array
of {n} verdicts, one per candidate, in the SAME ORDER as the input. Each verdict has:
- "is_product": bool
- "confidence": float in [0, 1]
- "price_hint": float or null
- "store_hint": string or null
- "freshness_signal": "blog" | "live_marketplace" | "static_catalog" | null
- "reason": string (short, max 80 chars)

Input candidates:
{candidates}

Output format: {{"verdicts": [v1, v2, ..., v{n}]}}"""


async def classify_batch(
    client: httpx.AsyncClient,
    candidates: list[dict],
    router_url: str,
    bearer_token: str,
    model: str,
) -> list[dict[str, Any]]:
    """Una sola llamada al router con TODOS los candidatos."""
    cand_payload = [
        {"i": i, "title": c.get("title"), "url": c.get("url"), "snippet": c.get("snippet")}
        for i, c in enumerate(candidates)
    ]
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + FEW_SHOT_EXAMPLES},
            {"role": "user", "content": BATCH_USER_TEMPLATE.format(
                n=len(candidates),
                candidates=json.dumps(cand_payload, ensure_ascii=False),
            )},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 128 * len(candidates),  # ~128 per candidate
        "stream": False,
    }
    resp = await client.post(
        f"{router_url}/v1/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {bearer_token}"},
        timeout=120.0,  # batch puede ser largo
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    parsed = json.loads(raw)
    verdicts = parsed.get("verdicts", [])
    return verdicts


async def main():
    router = settings.LLM_ROUTER_URL
    bearer = settings.LLM_ROUTER_BEARER_TOKEN

    cases = [json.loads(l) for l in FIX.read_text().splitlines() if l.strip()]
    print(f"Cases: {len(cases)}\n")

    async with httpx.AsyncClient() as client:
        resolved = await resolve_model(client, router, bearer)
        print(f"Resolved model: {resolved}\n")

        # warm up
        await classify_candidate(
            client, cases[0]["candidate"], asyncio.Semaphore(1),
            router, bearer, model=resolved
        )

        candidates = [c["candidate"] for c in cases]

        # ──────────────── Batch sizes ─────────────────
        results = {}
        for batch_size in (10, 25, 50):
            chunks = [candidates[i:i+batch_size] for i in range(0, len(candidates), batch_size)]
            print(f"--- Batch size {batch_size} ({len(chunks)} batches) ---")
            start = time.perf_counter()
            try:
                all_verdicts = []
                for chunk in chunks:
                    verdicts = await classify_batch(client, chunk, router, bearer, resolved)
                    all_verdicts.extend(verdicts)
                elapsed_s = time.perf_counter() - start
                got = len(all_verdicts)
                print(f"  Total: {elapsed_s:.1f}s  verdicts: {got}/{len(candidates)}")

                # Calidad
                tp = fp = tn = fn = 0
                for case, v in zip(cases, all_verdicts):
                    if not isinstance(v, dict):
                        continue
                    expected = case["expected_is_product"]
                    is_product = v.get("is_product", False)
                    confidence = v.get("confidence", 0.0)
                    freshness = v.get("freshness_signal")
                    keeps = is_product and confidence >= 0.4 and freshness != "blog"
                    if keeps and expected: tp += 1
                    elif keeps and not expected: fp += 1
                    elif not keeps and not expected: tn += 1
                    elif not keeps and expected: fn += 1
                prec = tp / max(tp + fp, 1)
                rec = tp / max(tp + fn, 1)
                results[f"batch_{batch_size}"] = {
                    "elapsed_s": round(elapsed_s, 2),
                    "verdicts_returned": got,
                    "tp": tp, "fp": fp, "tn": tn, "fn": fn,
                    "precision": round(prec, 4),
                    "recall": round(rec, 4),
                }
                print(f"  Precision: {prec:.2%}  Recall: {rec:.2%}\n")
            except Exception as e:
                print(f"  ERROR: {type(e).__name__}: {e}\n")
                results[f"batch_{batch_size}"] = {"error": str(e)}

    # Comparación final
    print("=== COMPARISON ===")
    print("Per-candidate sem(4) baseline (de script 03): ~35s, precision 92.5% recall 88.1%\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
