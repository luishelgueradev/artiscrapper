"""
Path híbrido: la heurística decide los "claros" (price_in_card OR known_store
OR blog_title OR document), el LLM SOLO decide los ambiguos.

Mide:
- % de candidatos que la heurística resuelve sola
- Latencia total (heurística ~0ms + LLM solo para los que quedan)
- Precision/Recall vs ground truth
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx  # noqa: E402

from src.artiscrapper.config import settings  # noqa: E402
from src.artiscrapper.llm import classify_candidate, resolve_model  # noqa: E402
from scripts.perfaudit.evaluate_heuristic_only import evaluate_candidate  # type: ignore  # noqa: E402

FIX = Path("tests/fixtures/llm/labelled.jsonl")
OUT = Path("scripts/perfaudit/07-hybrid.json")


async def main():
    cases = [json.loads(l) for l in FIX.read_text().splitlines() if l.strip()]
    router = settings.LLM_ROUTER_URL
    bearer = settings.LLM_ROUTER_BEARER_TOKEN

    # 1) Pre-clasificar con heurística
    pre_classified = []  # (case, keeps, reason) — heurística decidió
    ambiguous = []  # solo los que la heurística NO pudo resolver con confianza
    for case in cases:
        cand = case["candidate"]
        keeps, reason = evaluate_candidate(cand)
        if reason in ("ambiguous_no_price_no_known_store",):
            ambiguous.append(case)
        else:
            pre_classified.append((case, keeps, reason))

    print(f"Total: {len(cases)}")
    print(f"Heurística resolvió: {len(pre_classified)}")
    print(f"Quedan para LLM: {len(ambiguous)} ({len(ambiguous)*100//len(cases)}%)\n")

    # 2) Llamar al LLM solo para ambiguos (con sem 8 — concurrencia moderada)
    sem = asyncio.Semaphore(8)
    llm_t_start = time.perf_counter()
    llm_results = []
    if ambiguous:
        async with httpx.AsyncClient() as client:
            resolved = await resolve_model(client, router, bearer)
            verdicts = await asyncio.gather(
                *[classify_candidate(client, c["candidate"], sem, router, bearer, model=resolved)
                  for c in ambiguous]
            )
            for case, v in zip(ambiguous, verdicts):
                keeps = v.is_product and v.confidence >= 0.4 and v.freshness_signal != "blog"
                llm_results.append((case, keeps, f"llm:{v.reason[:30]}"))
    llm_t_total_s = time.perf_counter() - llm_t_start

    # 3) Resultados combinados
    all_decisions = pre_classified + llm_results
    tp = fp = tn = fn = 0
    for case, keeps, _ in all_decisions:
        expected = case["expected_is_product"]
        if keeps and expected: tp += 1
        elif keeps and not expected: fp += 1
        elif not keeps and not expected: tn += 1
        else: fn += 1

    n = len(all_decisions)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    accuracy = (tp + tn) / n
    f1 = 2 * (precision * recall) / max(precision + recall, 0.0001)

    summary = {
        "n_total": len(cases),
        "n_heuristic_decided": len(pre_classified),
        "n_llm_decided": len(ambiguous),
        "llm_phase_seconds": round(llm_t_total_s, 2),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "accuracy": round(accuracy, 4),
        "f1": round(f1, 4),
        "comparison_with_llm_pure": {
            "llm_pure_precision": 0.925,
            "llm_pure_recall": 0.881,
            "llm_pure_latency_s_sem4_real_world": 35,
            "llm_pure_latency_s_sem16_extrapolated": 16,
            "hybrid_precision": round(precision, 4),
            "hybrid_recall": round(recall, 4),
            "hybrid_latency_s": round(llm_t_total_s, 2),
            "speedup_vs_llm_pure_sem4": round(35 / max(llm_t_total_s, 0.01), 1),
        },
        "comparison_with_heuristic_pure": {
            "heuristic_pure_precision": 1.0,
            "heuristic_pure_recall": 0.7857,
            "hybrid_precision": round(precision, 4),
            "hybrid_recall": round(recall, 4),
            "recall_gain_pp": round((recall - 0.7857) * 100, 1),
            "precision_loss_pp": round((1.0 - precision) * 100, 1),
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
