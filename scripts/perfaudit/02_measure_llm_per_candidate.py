"""
Mide la efectividad y latencia del LLM curator candidato por candidato.

Usa los 50 candidatos labeled (`tests/fixtures/llm/labelled.jsonl`) como ground
truth. Llama `classify_candidate()` (función pura, una llamada por candidato).

Mide:
- Latencia por candidato (cold y warm — primer batch tira cold-load del modelo)
- Verdict crudo (is_product, confidence, reason, freshness)
- Precision/Recall vs ground truth (expected_is_product)
- Tiempos teóricos para los 50 candidatos: secuencial, sem(4), sem(8), sem(16)
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx  # noqa: E402

from src.artiscrapper.config import settings  # noqa: E402
from src.artiscrapper.llm import (  # noqa: E402
    classify_candidate,
    resolve_model,
    router_health_check,
)

FIX = Path("tests/fixtures/llm/labelled.jsonl")
OUT = Path("scripts/perfaudit/02-llm-per-candidate.jsonl")
SUM = Path("scripts/perfaudit/02-llm-per-candidate-summary.json")


async def main():
    router = settings.LLM_ROUTER_URL
    bearer = settings.LLM_ROUTER_BEARER_TOKEN

    print(f"Router: {router}  Configured model: {settings.LLM_MODEL}")

    healthy = await router_health_check(router, bearer)
    print(f"Router healthy: {healthy}")
    if not healthy:
        return

    resolved = await resolve_model(httpx.AsyncClient(), router, bearer)
    print(f"Resolved model: {resolved}\n")

    cases = [json.loads(l) for l in FIX.read_text().splitlines() if l.strip()]
    print(f"{len(cases)} labeled candidates loaded\n")

    sem = asyncio.Semaphore(1)  # uno-por-uno para medir latencia individual
    results = []

    async with httpx.AsyncClient() as client:
        for i, case in enumerate(cases):
            cand = case["candidate"]
            expected = case["expected_is_product"]
            expected_conf = case["expected_confidence_min"]

            start = time.perf_counter()
            v = await classify_candidate(
                client, cand, sem, router, bearer, model=resolved
            )
            elapsed_ms = (time.perf_counter() - start) * 1000

            # Aplicar la regla `should_keep` que aplica la app real
            #   is_product AND confidence >= 0.4 AND freshness != "blog"
            keeps = (
                v.is_product
                and v.confidence >= 0.4
                and v.freshness_signal != "blog"
            )

            tp = int(keeps and expected)
            fp = int(keeps and not expected)
            tn = int(not keeps and not expected)
            fn = int(not keeps and expected)

            row = {
                "id": case["id"],
                "elapsed_ms": elapsed_ms,
                "title": cand["title"][:80],
                "expected_is_product": expected,
                "expected_conf_min": expected_conf,
                "actual_is_product": v.is_product,
                "actual_confidence": v.confidence,
                "actual_reason": v.reason,
                "actual_freshness": v.freshness_signal,
                "keeps": keeps,
                "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            }
            results.append(row)
            print(
                f"[{i+1:>2}/{len(cases)}] {elapsed_ms:>6.0f}ms  "
                f"exp={expected!s:<5} got={v.is_product!s:<5} "
                f"conf={v.confidence:.2f} reason={v.reason[:20]:<22} "
                f"{cand['title'][:50]}"
            )

    # Save raw
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    # Summary metrics
    n = len(results)
    tp = sum(r["tp"] for r in results)
    fp = sum(r["fp"] for r in results)
    tn = sum(r["tn"] for r in results)
    fn = sum(r["fn"] for r in results)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    accuracy = (tp + tn) / n
    n_keep = sum(1 for r in results if r["keeps"])

    lat = sorted(r["elapsed_ms"] for r in results)
    p50 = lat[n // 2]
    p95 = lat[int(n * 0.95)]
    total_seq_s = sum(lat) / 1000

    n_timeout = sum(1 for r in results if r["actual_reason"] == "timeout")
    n_fallback = sum(1 for r in results if "fallback" in r["actual_reason"])

    # Latency simulation @ sem(K)
    # En batch real, las llamadas concurrent comparten KV-cache del system prompt,
    # por lo que con sem(K) la latencia total es ~total_seq/K + overhead constante
    sim = {k: total_seq_s / k for k in (1, 2, 4, 8, 12, 16)}

    summary = {
        "n": n,
        "model_resolved": resolved,
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "accuracy": round(accuracy, 4),
        "kept_count": n_keep,
        "dropped_count": n - n_keep,
        "ground_truth_products": sum(1 for c in cases if c["expected_is_product"]),
        "ground_truth_non_products": sum(1 for c in cases if not c["expected_is_product"]),
        "latency_ms_p50": p50,
        "latency_ms_p95": p95,
        "latency_ms_min": lat[0],
        "latency_ms_max": lat[-1],
        "total_sequential_s": round(total_seq_s, 1),
        "estimated_with_sem": {f"sem_{k}": round(v, 1) for k, v in sim.items()},
        "n_fallback_verdicts": n_fallback,
        "n_timeout_verdicts": n_timeout,
    }

    SUM.write_text(json.dumps(summary, indent=2))
    print(f"\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"\nRaw: {OUT}\nSummary: {SUM}")


if __name__ == "__main__":
    asyncio.run(main())
