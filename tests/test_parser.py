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
