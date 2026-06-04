"""
Mide el costo del visit pass: visitar N candidatos para extraer precio
de las páginas que no lo trajeron en el SERP.

En el path real, visit pass corre solo para candidatos con `has_price=False`,
y tiene Semáforo global(8) + per-host(2). Mide:
- Tiempo promedio por visit
- Distribución por host
- Cuántos visit_failed típicos
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.artiscrapper.visit import visit_candidates  # noqa: E402

FIX = Path("tests/fixtures/llm/labelled.jsonl")
OUT = Path("scripts/perfaudit/08-visit-pass.json")


async def main():
    cases = [json.loads(l) for l in FIX.read_text().splitlines() if l.strip()]
    # Filtrar candidatos SIN price_in_card (los que sí lo tienen no se visitan)
    no_price = [
        c["candidate"] for c in cases
        if not c["candidate"].get("price_in_card")
        and c["expected_is_product"]  # solo productos legítimos
    ]
    print(f"Candidatos sin price_in_card a visitar: {len(no_price)}")

    if not no_price:
        print("Sin candidatos a visitar — abort")
        return

    # Sample acotado para no agotar timeouts
    sample = no_price[:10]
    print(f"Sample: {len(sample)}\n")

    start = time.perf_counter()
    results = await visit_candidates(sample, visit_timeout_s=10)
    total_s = time.perf_counter() - start

    visited = [r for r in results if "visit_failed" not in r.get("flags", [])]
    failed = [r for r in results if "visit_failed" in r.get("flags", [])]
    extracted_price = [r for r in results if r.get("price")]
    extracted_freshness = [r for r in results if r.get("date_modified") or r.get("date_published")]

    summary = {
        "n_sample": len(sample),
        "total_seconds": round(total_s, 2),
        "per_visit_avg_ms": round(total_s * 1000 / len(sample), 0),
        "visited_count": len(visited),
        "failed_count": len(failed),
        "extracted_price_count": len(extracted_price),
        "extracted_freshness_count": len(extracted_freshness),
        "visit_success_rate": round(len(visited) / len(sample), 4),
        "price_extraction_rate": round(len(extracted_price) / len(visited), 4) if visited else 0,
        "estimated_for_15_candidates_s": round(total_s * 15 / len(sample), 1),
        "estimated_for_30_candidates_s": round(total_s * 30 / len(sample), 1),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
