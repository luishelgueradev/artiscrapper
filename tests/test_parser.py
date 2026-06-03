"""
Unit tests for the SERP parser cascade, URL canonicalization, and junk blocklist.
Implemented against search.py (Task 3). Tests are real (not stubs) for parser functions
that are implemented in this plan.
SEARCH-04: cascade. SEARCH-05: canonicalize + dedupe. SEARCH-06: junk blocklist.
"""

import glob
import os
import pathlib

from src.artiscrapper.search import (
    build_serp_url,
    canonicalize_url,
    dedupe,
    is_junk,
    parse_serp,
)

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures" / "serp"


def test_cascade_exhausted_alert(monkeypatch):
    """
    D4: When all organic selectors return 0 results, parse_cascade_exhausted warning fires.
    Monkeypatch ORGANIC_SELECTORS to empty-match only selectors.
    Captures structlog output by patching the log object's warning method.
    """
    import src.artiscrapper.search as search_mod

    # Patch to selectors that won't match empty HTML
    monkeypatch.setattr(search_mod, "ORGANIC_SELECTORS", ["div.THIS_SELECTOR_WILL_NEVER_MATCH"])
    monkeypatch.setattr(search_mod, "CAROUSEL_SELECTORS", [])

    # Capture structlog warnings by patching the module-level log
    warnings_logged = []
    original_warning = search_mod.log.warning

    def capture_warning(event, **kw):
        warnings_logged.append(event)
        return original_warning(event, **kw)

    monkeypatch.setattr(search_mod.log, "warning", capture_warning)

    parse_serp("<html><body><p>Nothing here</p></body></html>")

    assert "parse_cascade_exhausted" in warnings_logged, (
        f"Expected parse_cascade_exhausted warning, got: {warnings_logged}"
    )


def test_canonicalize():
    """SEARCH-05: canonicalize_url strips utm_*, gclid, ved and lowercases netloc."""
    raw = "https://www.Example.com/product?utm_source=google&gclid=abc&ved=xyz&id=42"
    clean = canonicalize_url(raw)
    assert "utm_source" not in clean
    assert "gclid" not in clean
    assert "ved" not in clean
    assert "id=42" in clean, "Non-tracking param 'id' should be preserved"
    assert "example.com" in clean, "netloc should be lowercased"

    # Dedupe: same canonical URL from two different raw URLs
    url_a = "https://tienda.com/producto/123?utm_campaign=mail"
    url_b = "https://tienda.com/producto/123?utm_source=newsletter"
    assert canonicalize_url(url_a) == canonicalize_url(url_b), (
        "Canonicalized URLs with only tracking params differ should be equal"
    )


def test_blocklist():
    """SEARCH-06/D9: Junk-domain blocklist drops youtube, fandom, wikipedia, reddit."""
    assert is_junk("https://www.youtube.com/watch?v=abc"), "youtube.com should be junk"
    assert is_junk("https://youtube.com/results?search_query=test"), "youtube.com should be junk"
    assert is_junk("https://repuestos.fandom.com/wiki/Filtro"), ".fandom.com should be junk"
    assert is_junk("https://es.wikipedia.org/wiki/Automotor"), "wikipedia.org should be junk"
    assert is_junk("https://www.reddit.com/r/argentina/"), "reddit.com should be junk"
    assert is_junk("https://reddit.com/search?q=repuesto"), "reddit.com should be junk"
    assert is_junk("https://medium.com/@user/article"), "medium.com should be junk"

    # Non-junk domains
    assert not is_junk("https://www.mercadolibre.com.ar/producto"), "MELI is NOT junk (LLM decides)"
    assert not is_junk("https://autodo.com.ar/producto"), "AR auto store is NOT junk"
    assert not is_junk("https://www.falabella.com.ar/product"), "falabella is NOT junk"


def test_parse_serp_fixtures():
    """SEARCH-04: Parser extracts candidates from all 10 Phase 1 SERP fixtures."""
    fixture_files = sorted(glob.glob(str(FIXTURES_DIR / "*.html")))
    assert len(fixture_files) == 10, f"Expected 10 SERP fixtures, got {len(fixture_files)}"

    for filepath in fixture_files:
        name = os.path.basename(filepath)
        html = pathlib.Path(filepath).read_text(encoding="utf-8", errors="replace")
        results = parse_serp(html)
        assert len(results) > 0, (
            f"parse_serp returned 0 results for fixture '{name}' — "
            "Phase 1 confirmed tF2Cxc primary selector should yield results"
        )


def test_carousel_extracts_prices_from_fixtures():
    """
    SEARCH-04 regression guard — the carousel extractor was originally a stub that
    required <a href> inside the card (Google uses JS click handlers, so it never
    matched). All 20+ carousel items per fixture were silently dropped, and the
    price selectors (.price/.precio) didn't match Google's obfuscated classes either.

    After the regex-first refactor, every fixture with a Google Shopping carousel
    should yield at least 8 carousel candidates with prices, and the per-fixture
    'with-price' count should be substantially above the pre-fix baseline.
    """
    expectations = {
        # name → (min_carousel_items, min_with_price)
        "01-pelota_playera_quico.html": (15, 18),
        "02-filtro_aceite_ford_focus.html": (25, 25),
        "03-amortiguador_trasero_peugeot_208.html": (8, 12),
        "04-buja_ngk_bosch.html": (15, 15),
        "05-correa_distribucion_fiat_cronos.html": (8, 10),
        "06-disco_freno_renault_sandero.html": (8, 12),
        "07-rotula_direccion_vw_gol.html": (25, 25),
        "08-kit_embrague_chevrolet_onix.html": (25, 25),
        "09-termostato_corsa_classic.html": (12, 15),
        # 10-balatas: Phase 1 confirmed this fixture has NO carousel (empty carousel
        # column in survey); only organic results — no minimum carousel guarantee.
    }
    for name, (min_carousel, min_with_price) in expectations.items():
        html = (FIXTURES_DIR / name).read_text(encoding="utf-8", errors="replace")
        cands = parse_serp(html)
        carousel_count = sum(1 for c in cands if "carousel" in c.get("flags", []))
        with_price = sum(1 for c in cands if c.get("price_in_card"))
        assert carousel_count >= min_carousel, (
            f"{name}: carousel candidates regressed: got {carousel_count}, "
            f"expected ≥{min_carousel}. Likely Google rotated the Ez5pwe selector."
        )
        assert with_price >= min_with_price, (
            f"{name}: candidates-with-price regressed: got {with_price}, "
            f"expected ≥{min_with_price}. Check _extract_commercial_signals regex."
        )


def test_carousel_url_is_synthetic_when_no_direct_link():
    """Carousel items have no <a href>; URL is a Google search fallback flagged
    with 'synthetic_url'. Consumers can show it as 'search this product' rather
    than expecting a direct PDP link."""
    html = (FIXTURES_DIR / "01-pelota_playera_quico.html").read_text(encoding="utf-8")
    cands = parse_serp(html)
    carousel_items = [c for c in cands if "carousel" in c.get("flags", [])]
    assert len(carousel_items) > 0, "carousel items missing from pelota_quico fixture"
    for c in carousel_items:
        assert "synthetic_url" in c.get("flags", []), (
            f"carousel item missing synthetic_url flag: {c['url']!r}"
        )
        assert c["url"].startswith("https://www.google.com/search?q="), (
            f"carousel synthetic URL should be a Google search fallback, got {c['url']!r}"
        )
        assert c.get("price_in_card"), (
            "carousel candidate should always have price_in_card (filter in extractor)"
        )


def test_commercial_signals_extracted_from_node_text():
    """Regex-based signal extraction: installments, stock, free shipping, store_hint."""
    html = (FIXTURES_DIR / "01-pelota_playera_quico.html").read_text(encoding="utf-8")
    cands = parse_serp(html)
    # At least some candidates should carry each signal type
    assert sum(1 for c in cands if c.get("installments")) >= 5, (
        "installments regex should capture at least 5 carousel items"
    )
    assert sum(1 for c in cands if c.get("store_hint")) >= 10, (
        "store_hint regex should capture trailing domain from carousel + organic"
    )
    assert sum(1 for c in cands if c.get("stock")) >= 1, (
        "stock regex should catch 'agotado' / 'in stock' indicators when present"
    )


def test_build_serp_url():
    """SEARCH-03/D3: build_serp_url includes pws=0&safe=off, no site: operator."""
    url_a = build_serp_url("filtro aceite ford focus")
    assert "pws=0" in url_a or "pws%3D0" in url_a or "pws=0" in url_a
    assert "safe=off" in url_a or "safe%3Doff" in url_a or "safe=off" in url_a
    assert "site:" not in url_a, "D3: no site: operator"
    assert "mercadolibre" not in url_a, "URL A should not contain mercadolibre"

    url_b = build_serp_url("filtro aceite ford focus", meli=True)
    assert "mercadolibre" in url_b, "URL B should include mercadolibre"
    assert "site:" not in url_b, "D3: no site: operator"


def test_dedupe():
    """SEARCH-05: dedupe removes candidates with same canonical URL."""
    candidates = [
        {"url": "https://tienda.com/producto?utm_source=a", "title": "Prod A"},
        {"url": "https://tienda.com/producto?utm_source=b", "title": "Prod A dup"},
        {"url": "https://otro.com/item/1", "title": "Prod B"},
    ]
    deduped = dedupe(candidates)
    assert len(deduped) == 2, f"Expected 2 unique candidates, got {len(deduped)}"
    urls = [c["url"] for c in deduped]
    # All canonical URLs should be unique
    assert len(set(urls)) == len(urls), "Deduped list has duplicate canonical URLs"
