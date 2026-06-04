"""
Evalúa qué calidad tendríamos si SACÁRAMOS el LLM y usáramos solo
heurística (blocklist + price-in-card + freshness signals del extractor).

Comparación contra ground truth: precision, recall, F1.

Heurística simulada:
- keeps si: !is_junk(url) AND (has_price_in_card OR is_meli_or_known_store)
- descarta si: is_junk OR pure-blog-signals (no precio + URL/title de blog)
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.artiscrapper.search import is_junk  # noqa: E402

FIX = Path("tests/fixtures/llm/labelled.jsonl")
OUT = Path("scripts/perfaudit/05-heuristic-vs-truth.json")

# Indicadores de "es un producto vendible"
KNOWN_STORES = frozenset({
    "mercadolibre.com.ar", "mercadolibre.com", "amazon.com.ar",
    "garbarino.com", "fravega.com", "tiendamia.com",
    "musimundo.com", "carrefour.com.ar", "cetrogar.com.ar",
    "compraonline.com.ar",
})

# Indicadores de blog/contenido no-comprable
BLOG_TITLE_PATTERNS = (
    "como saber", "qué elegir", "qué es", "diferencia entre",
    "tabla de equivalencias", "comparativa", "cada cuánto",
    "guía", "tutorial", "review", "opinión",
)
DOCUMENT_PATTERNS = (".pdf", ".doc", ".docx")
FORUM_PATTERNS = ("reddit.com", "/forum/", "/foro/")


def evaluate_candidate(cand: dict) -> tuple[bool, str]:
    """Devuelve (keeps, reason)."""
    url = cand.get("url") or ""
    title = (cand.get("title") or "").lower()
    snippet = (cand.get("snippet") or "").lower()
    price_in_card = cand.get("price_in_card")

    # Junk URL? → descartar
    if is_junk(url):
        return False, "junk_domain"

    # Documento (PDF, DOC)? → descartar
    if any(p in url.lower() for p in DOCUMENT_PATTERNS):
        return False, "document"

    # Foro? → descartar
    if any(p in url.lower() for p in FORUM_PATTERNS):
        return False, "forum"

    # Title con marca de "contenido"? → descartar
    if any(p in title for p in BLOG_TITLE_PATTERNS):
        return False, "blog_title"

    # Indicador positivo 1: trae precio en card del SERP
    if price_in_card:
        return True, "price_in_card"

    # Indicador positivo 2: store reconocida en host
    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
        for store in KNOWN_STORES:
            if host.endswith(store):
                return True, f"known_store:{store}"
    except Exception:
        pass

    # Sin price + sin store conocida → ambigüo, descartar
    return False, "ambiguous_no_price_no_known_store"


def main():
    cases = [json.loads(l) for l in FIX.read_text().splitlines() if l.strip()]
    print(f"Cases: {len(cases)}\n")

    tp = fp = tn = fn = 0
    by_reason = {}
    rows = []

    for case in cases:
        cand = case["candidate"]
        expected = case["expected_is_product"]
        keeps, reason = evaluate_candidate(cand)

        by_reason[reason] = by_reason.get(reason, 0) + 1

        if keeps and expected: tp += 1
        elif keeps and not expected: fp += 1
        elif not keeps and not expected: tn += 1
        else: fn += 1

        rows.append({
            "id": case["id"],
            "title": cand["title"][:80],
            "expected": expected,
            "keeps": keeps,
            "reason": reason,
        })

    n = len(cases)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    accuracy = (tp + tn) / n
    f1 = 2 * (precision * recall) / max(precision + recall, 0.0001)
    n_keep = sum(1 for r in rows if r["keeps"])

    summary = {
        "n": n,
        "kept_count": n_keep,
        "dropped_count": n - n_keep,
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "accuracy": round(accuracy, 4),
        "f1": round(f1, 4),
        "by_reason": by_reason,
        "latency_ms": 0,  # heurística pura, instantánea
        "false_negatives_detail": [
            {"id": r["id"], "title": r["title"], "reason": r["reason"]}
            for r in rows if not r["keeps"] and r["expected"]
        ],
        "false_positives_detail": [
            {"id": r["id"], "title": r["title"], "reason": r["reason"]}
            for r in rows if r["keeps"] and not r["expected"]
        ],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"\nOutput → {OUT}")


if __name__ == "__main__":
    main()
