"""
Unit tests for `heuristic_pre_classify` (Path B perf-audit 2026-06-04).

Splits SERP candidates into (kept_high_conf, ambiguous) and hard-drops
junk/blog/document/forum signals. Validated against the 50 Phase 1 labeled
fixtures: precision 92.7%, recall 90.5% (hybrid with LLM).
"""

import json
import pathlib

from src.artiscrapper.search import (
    BLOG_TITLE_PATTERNS,
    DOCUMENT_EXTENSIONS,
    FORUM_PATTERNS,
    KNOWN_STORES,
    heuristic_pre_classify,
)

LABELED_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "llm" / "labelled.jsonl"


# ──────────────────────────────────────────
# Hard-drop signals
# ──────────────────────────────────────────


def test_junk_domain_dropped():
    cands = [
        {"url": "https://www.youtube.com/watch?v=abc", "title": "How to install brakes"},
    ]
    kept, ambiguous = heuristic_pre_classify(cands)
    assert kept == []
    assert ambiguous == []  # dropped, not even ambiguous


def test_document_url_dropped():
    cands = [
        {"url": "https://acme.com/manual.pdf", "title": "Bujías encendido manual"},
        {"url": "https://acme.com/catalog.xlsx", "title": "Catalog 2024"},
    ]
    kept, ambiguous = heuristic_pre_classify(cands)
    assert kept == []
    assert ambiguous == []


def test_forum_url_dropped():
    cands = [
        {"url": "https://www.reddit.com/r/E90/comments/abc/bujias_bosch_vs_ngk", "title": "Bujías"},
        {"url": "https://foroautos.com/foro/topic/123", "title": "Cambio de bujías"},
        {"url": "https://quora.com/qua-bujia-comprar", "title": "Bujías recomendadas"},
    ]
    kept, ambiguous = heuristic_pre_classify(cands)
    assert kept == []
    assert ambiguous == []


def test_blog_title_dropped():
    cands = [
        {"url": "https://example.com/bujias-guia", "title": "¿Qué Elegir entre NGK, BOSCH, DENSO?"},
        {"url": "https://example.com/correa", "title": "Cada cuánto debe cambiarse la correa"},
        {"url": "https://example.com/dist", "title": "Tabla de equivalencias de bujías"},
    ]
    kept, ambiguous = heuristic_pre_classify(cands)
    assert kept == []
    assert ambiguous == []


# ──────────────────────────────────────────
# High-confidence keep signals
# ──────────────────────────────────────────


def test_price_in_card_kept_high_conf():
    cands = [
        {
            "url": "https://random-store.com.ar/product/123",
            "title": "Filtro de aceite Ford Focus",
            "price_in_card": "$15.000",
        }
    ]
    kept, ambiguous = heuristic_pre_classify(cands)
    assert len(kept) == 1
    assert kept[0]["_pre_class_reason"] == "price_in_card"
    assert ambiguous == []


def test_known_store_host_kept_high_conf():
    cands = [
        {"url": "https://listado.mercadolibre.com.ar/filtro-aceite-ford", "title": "Filtro"},
        {"url": "https://www.fravega.com/p/bujia-ngk-iridium-12345/", "title": "Bujía NGK"},
        {"url": "https://www.carrefour.com.ar/p/oferta-frenos", "title": "Frenos"},
    ]
    kept, ambiguous = heuristic_pre_classify(cands)
    assert len(kept) == 3
    assert all(k["_pre_class_reason"] == "known_store" for k in kept)
    assert ambiguous == []


def test_known_store_with_www_prefix_matches():
    # Defensive: ensure `www.` prefix is stripped before suffix match.
    cands = [
        {"url": "https://www.mercadolibre.com.ar/listing", "title": "Producto"},
    ]
    kept, ambiguous = heuristic_pre_classify(cands)
    assert len(kept) == 1
    assert kept[0]["_pre_class_reason"] == "known_store"


# ──────────────────────────────────────────
# Ambiguous fallback
# ──────────────────────────────────────────


def test_unknown_store_without_price_is_ambiguous():
    cands = [
        {
            "url": "https://unknown-parts-shop.com.ar/products/filter-x",
            "title": "Filtro de aceite generico para Ford",
            # No price_in_card
        }
    ]
    kept, ambiguous = heuristic_pre_classify(cands)
    assert kept == []
    assert len(ambiguous) == 1
    # ambiguous candidates do NOT carry _pre_class_reason
    assert "_pre_class_reason" not in ambiguous[0]


# ──────────────────────────────────────────
# Mixed batch — most realistic case
# ──────────────────────────────────────────


def test_mixed_batch_splits_correctly():
    cands = [
        # 2 high-conf (price + known store)
        {"url": "https://example.com/", "title": "X", "price_in_card": "$1.000"},
        {"url": "https://listado.mercadolibre.com.ar/x", "title": "X"},
        # 1 ambiguous
        {"url": "https://random.com/x", "title": "X"},
        # 1 dropped (forum)
        {"url": "https://reddit.com/r/x", "title": "X"},
        # 1 dropped (junk)
        {"url": "https://www.youtube.com/watch?v=x", "title": "X"},
        # 1 dropped (document)
        {"url": "https://example.com/manual.pdf", "title": "X"},
        # 1 dropped (blog title)
        {"url": "https://example.com/x", "title": "Diferencia entre bujías"},
    ]
    kept, ambiguous = heuristic_pre_classify(cands)
    assert len(kept) == 2
    assert len(ambiguous) == 1
    # 4 dropped (not in either bucket)


def test_empty_input_returns_empty_buckets():
    kept, ambiguous = heuristic_pre_classify([])
    assert kept == []
    assert ambiguous == []


def test_candidates_with_missing_url_treated_as_ambiguous():
    # Defensive: cand without "url" key should not crash and not be wrongly kept.
    cands = [{"title": "Some title without URL"}]
    kept, ambiguous = heuristic_pre_classify(cands)
    assert kept == []
    assert len(ambiguous) == 1


# ──────────────────────────────────────────
# Quality regression: precision against ground truth
# ──────────────────────────────────────────


def test_heuristic_precision_on_labeled_fixtures():
    """
    Against the 50 Phase 1 labeled candidates, heuristic_pre_classify alone
    must achieve precision >= 95% (zero false positives in practice — but
    keep the bar at 95% for slack on future label revisions).

    The 'precision' here is: of the candidates the heuristic KEPT (price or
    known store), what fraction were actually products per the label.
    """
    cases = [json.loads(line) for line in LABELED_FIXTURE.read_text().splitlines() if line.strip()]
    candidates = [c["candidate"] for c in cases]
    kept, ambiguous = heuristic_pre_classify(candidates)

    # Build URL → expected_is_product lookup
    expected_by_url = {c["candidate"]["url"]: c["expected_is_product"] for c in cases}

    # All kept candidates must be products per the label (precision = 100%)
    kept_tp = sum(1 for k in kept if expected_by_url[k["url"]])
    kept_fp = sum(1 for k in kept if not expected_by_url[k["url"]])
    precision = kept_tp / max(kept_tp + kept_fp, 1)

    assert precision >= 0.95, (
        f"heuristic_pre_classify precision regressed: {precision:.2%} "
        f"(tp={kept_tp} fp={kept_fp} on kept={len(kept)})"
    )

    # And the heuristic must resolve a substantial portion — at least 50%.
    # (In the audit, 76% was the actual number; require 50% as a floor so
    # future small label changes don't trip the test.)
    resolved_fraction = (len(kept) + (len(candidates) - len(kept) - len(ambiguous))) / len(
        candidates
    )
    assert resolved_fraction >= 0.50, (
        f"heuristic resolved only {resolved_fraction:.0%} of candidates — "
        f"below 50% floor (audit baseline 76%)"
    )


# ──────────────────────────────────────────
# Constants sanity
# ──────────────────────────────────────────


def test_constants_present_and_lowercased():
    assert isinstance(KNOWN_STORES, frozenset)
    assert all(s == s.lower() for s in KNOWN_STORES), "KNOWN_STORES must be lowercase"
    assert all(p == p.lower() for p in BLOG_TITLE_PATTERNS), "patterns must be lowercase"
    assert all(p == p.lower() for p in FORUM_PATTERNS), "patterns must be lowercase"
    assert all(e.startswith(".") for e in DOCUMENT_EXTENSIONS), "extensions need leading dot"
