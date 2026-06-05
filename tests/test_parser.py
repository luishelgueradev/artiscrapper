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
    """SEARCH-04: Parser extracts candidates from all 10 Phase 1 SERP fixtures.
    Phase 1 fixtures are named NN-<slug>.html (01..10). Later phases may add
    fixtures with other naming conventions (e.g. pla_unit_*.html for 0.2.1
    PARITY-04) — filter to Phase 1's numbered set so this test stays stable.
    """
    fixture_files = sorted(glob.glob(str(FIXTURES_DIR / "[0-9][0-9]-*.html")))
    assert len(fixture_files) == 10, f"Expected 10 Phase 1 SERP fixtures, got {len(fixture_files)}"

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


# ──────────────────────────────────────────
# Phase 0.2.1 — pla-unit extractor tests (PARITY-02)
# ──────────────────────────────────────────

from src.artiscrapper.search import _extract_pla_unit, PLA_SELECTORS  # noqa: E402
from selectolax.parser import HTMLParser  # noqa: E402


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def test_pla_unit_extracts_4_products_from_robotech_fixture():
    """Wave-0: robotech fixture has 4 pla-unit cards with MELI canonical URLs.
    Frozen 2026-06-05 from /tmp/robotech-serp.html (Google auction-volatile;
    a re-capture of the same query may return 0 or N pla-units).
    """
    html = _load_fixture("pla_unit_robotech.html")
    tree = HTMLParser(html)
    extracted = [_extract_pla_unit(n) for n in tree.css("div.pla-unit")]
    extracted = [c for c in extracted if c]
    assert len(extracted) >= 4, f"Expected >=4 pla-units, got {len(extracted)}"
    assert all("mercadolibre.com.ar" in c["url"] for c in extracted)
    assert all(c["has_price"] for c in extracted)


def test_pla_unit_extracts_30_products_from_zapatillas_fixture():
    """Wave-0: zapatillas fixture has 30+ pla-unit cards across diverse stores.
    Validates the extractor works for non-MELI stores (sporting, nike,
    stockcenter, etc.) without MELI-specific hardcoding.
    """
    html = _load_fixture("pla_unit_zapatillas.html")
    tree = HTMLParser(html)
    extracted = [_extract_pla_unit(n) for n in tree.css("div.pla-unit")]
    extracted = [c for c in extracted if c]
    assert len(extracted) >= 30, f"Expected >=30 pla-units, got {len(extracted)}"
    # Diverse stores: not all MELI
    stores = {c["store_hint"] for c in extracted if c.get("store_hint")}
    assert len(stores) >= 3, f"Expected diverse stores, got {stores}"


def test_pla_unit_no_aclk_urls():
    """The /aclk? redirect <a> is a display:none tracking pixel; extractor must skip it."""
    html = _load_fixture("pla_unit_robotech.html")
    tree = HTMLParser(html)
    extracted = [_extract_pla_unit(n) for n in tree.css("div.pla-unit")]
    extracted = [c for c in extracted if c]
    for c in extracted:
        assert "/aclk?" not in c["url"], f"pla-unit returned aclk URL: {c['url']}"
        assert c["url"].startswith("http"), f"pla-unit URL not http: {c['url']}"


def test_pla_unit_sponsored_flag():
    """All pla-units carry 'sponsored' + 'pla_unit' flags for downstream policy."""
    html = _load_fixture("pla_unit_robotech.html")
    tree = HTMLParser(html)
    extracted = [_extract_pla_unit(n) for n in tree.css("div.pla-unit")]
    extracted = [c for c in extracted if c]
    for c in extracted:
        assert "pla_unit" in c["flags"]
        assert "sponsored" in c["flags"]


def test_pla_selectors_exported():
    """Verify PLA_SELECTORS is a non-empty list with the canonical container selector."""
    assert PLA_SELECTORS, "PLA_SELECTORS must be non-empty"
    assert "div.pla-unit" in PLA_SELECTORS


# ──────────────────────────────────────────
# Phase 0.2.1 — _PRICE_RE v2 tests (PARITY-03)
# ──────────────────────────────────────────

import pytest  # noqa: E402
from src.artiscrapper.search import _PRICE_RE, _extract_commercial_signals  # noqa: E402


@pytest.mark.parametrize("text,expected", [
    ("Threezero figura $410.420,311001hobbies.es", "$410.420,31"),
    ("Yr-052F $\xa01.397.000,00 ahora", "$\xa01.397.000,00"),
    ("$45.885,00x 6Tigre.com.ar", "$45.885,00"),
    ("Precio: $5.000,00 ahora", "$5.000,00"),
    ("$ 12.345,67/mes x 6 cuotas", "$ 12.345,67"),
    ("Total $920.000,00 fin", "$920.000,00"),
])
def test_price_regex_matches_normal_ar_format(text, expected):
    m = _PRICE_RE.search(text)
    assert m is not None, f"No match in {text!r}"
    assert m.group(0) == expected, f"Got {m.group(0)!r}, expected {expected!r}"


def test_price_regex_no_bleed_into_store_digits():
    """Bug regression: text '$410.420,311001hobbies.es' must NOT match '$410.420,311001'.
    Real-world source: carousel item
      'threezero Figura a escala 1:6 de Robo-Dou$ 410.420,311001hobbies.es'
    """
    text = "threezero Figura a escala 1:6 de Robo-Dou$\xa0410.420,311001hobbies.esy más5,0(2)"
    m = _PRICE_RE.search(text)
    assert m is not None
    assert m.group(0).rstrip() == "$\xa0410.420,31", f"Bleeding bug back: {m.group(0)!r}"


def test_price_regex_handles_ars_integer():
    """ARS without decimals (legacy AR format)."""
    m = _PRICE_RE.search("ARS 5000")
    assert m is not None
    assert m.group(0) == "ARS 5000"


def test_price_regex_handles_us_dollar_integer():
    """U$S without decimals (legacy format)."""
    m = _PRICE_RE.search("U$S 5000")
    assert m is not None
    assert m.group(0) == "U$S 5000"


def test_price_regex_filtered_by_short_digit_count():
    """'$5' is too short — _extract_commercial_signals must filter by digits >= 3.
    The new regex pattern won't even match $5 (requires at least 3 digits).
    """
    sigs = _extract_commercial_signals("hola $5 chau")
    assert "price_in_card" not in sigs, f"Short price not filtered: {sigs}"


# ── build_serp_url paging (Phase 0.2.3, PAGE2-01) ──


def test_build_serp_url_page1_omits_start_param():
    """Backward compat: page=1 (default) produces the same URL as v0.1.

    A change here would break consumers replaying v0.1 fixtures against
    v0.2.3 code, so we hard-pin the literal URL prefix.
    """
    u1 = build_serp_url("filtro aceite ford focus")
    u_default = build_serp_url("filtro aceite ford focus", page=1)
    assert u1 == u_default
    assert "&start=" not in u1


def test_build_serp_url_page2_emits_start_param():
    """page=2 must add &start=10 per Google convention."""
    u2 = build_serp_url("filtro aceite ford focus", page=2)
    assert "&start=10" in u2
    # And page=3 → start=20, page=10 → start=90
    u3 = build_serp_url("q", page=3)
    u10 = build_serp_url("q", page=10)
    assert "&start=20" in u3
    assert "&start=90" in u10


def test_build_serp_url_rejects_page_zero_and_above_ten():
    """Out-of-range page values raise ValueError."""
    import pytest
    with pytest.raises(ValueError):
        build_serp_url("q", page=0)
    with pytest.raises(ValueError):
        build_serp_url("q", page=11)
    with pytest.raises(ValueError):
        build_serp_url("q", page=-1)
