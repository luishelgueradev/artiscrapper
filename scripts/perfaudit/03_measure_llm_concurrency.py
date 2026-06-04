"""
Mide la concurrencia REAL del LLM router. Hipótesis: el código usa
Semaphore(LLM_CONCURRENCY) pero el router/Ollama serializa internamente.

Prueba: mismo set de 50 candidatos con sem={1, 2, 4, 8, 16}. Si el router
acepta concurrencia, total_time(sem=K) ≈ total_seq / K. Si serializa,
total_time(sem=K) ≈ total_seq independientemente de K.
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

FIX = Path("tests/fixtures/llm/labelled.jsonl")
OUT = Path("scripts/perfaudit/03-llm-concurrency.json")


async def run_with_sem(client, cases, resolved, router, bearer, sem_size):
    sem = asyncio.Semaphore(sem_size)
    start = time.perf_counter()
    results = await asyncio.gather(
        *[classify_candidate(client, c["candidate"], sem, router, bearer, model=resolved)
          for c in cases]
    )
    elapsed_s = time.perf_counter() - start
    return elapsed_s, results


async def main():
    router = settings.LLM_ROUTER_URL
    bearer = settings.LLM_ROUTER_BEARER_TOKEN
    cases = [json.loads(l) for l in FIX.read_text().splitlines() if l.strip()]
    print(f"Cases: {len(cases)}")

    async with httpx.AsyncClient() as client:
        resolved = await resolve_model(client, router, bearer)
        print(f"Resolved model: {resolved}\n")

        results = {}
        for sem_size in (1, 2, 4, 8, 16):
            # warm up con 1 llamada para evitar cold load
            await classify_candidate(
                client, cases[0]["candidate"], asyncio.Semaphore(1),
                router, bearer, model=resolved
            )
            print(f"--- Sem({sem_size}) ---")
            elapsed_s, _ = await run_with_sem(client, cases, resolved, router, bearer, sem_size)
            per_call_avg = elapsed_s * 1000 / len(cases)
            speedup = results.get(1, elapsed_s) / elapsed_s if 1 in results else 1.0
            print(f"  Total: {elapsed_s:.1f}s  avg/call: {per_call_avg:.0f}ms  speedup_vs_sem1: {speedup:.2f}x")
            results[sem_size] = elapsed_s

    summary = {
        "n_candidates": len(cases),
        "model": resolved,
        "results_seconds": {f"sem_{k}": round(v, 2) for k, v in results.items()},
        "results_per_call_ms_avg": {
            f"sem_{k}": round(v * 1000 / len(cases), 0) for k, v in results.items()
        },
        "speedup_vs_sem1": {
            f"sem_{k}": round(results[1] / v, 2) for k, v in results.items()
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2))
    print(f"\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
