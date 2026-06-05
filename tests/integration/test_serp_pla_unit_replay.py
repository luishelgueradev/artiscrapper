"""Phase 0.2.1 (PARITY-04 / PARITY-05) — Integration test fixture-replay for pla-unit.

Verifies end-to-end that parse_serp() integrates the pla-unit pass correctly
with the existing organic cascade + carousel loop, AND that the regex precio v2
doesn't regress any existing carousel coverage.

Source fixtures captured 2026-06-05 from Cloak (see
.planning/PARSER-VISUAL-PARITY-2026-06-05.md). Frozen at that date — Google
Shopping auction is volatile and a re-capture of the same query may not
return the same pla-unit count, so we pin to these specific fixtures.
"""
import re
from pathlib import Path

from src.artiscrapper.search import parse_serp

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "serp"


def _load(name: str) -> str:
    return (FIXTURE_DIR / name).read_text()


def test_robotech_returns_pla_unit_products():
    """parse_serp on robotech fixture yields 4+ pla-units with MELI canonical URLs.
    Also: carousel coverage >= 25 (no regression from Wave 1 patches)."""
    cands = parse_serp(_load("pla_unit_robotech.html"))
    pla = [c for c in cands if "pla_unit" in (c.get("flags") or [])]
    carousel = [c for c in cands if "carousel" in (c.get("flags") or [])]
    assert len(pla) >= 4, f"Expected >=4 pla, got {len(pla)}"
    assert all("mercadolibre.com.ar" in c["url"] for c in pla)
    assert all(c["has_price"] for c in pla)
    assert len(carousel) >= 25, f"Carousel regression: {len(carousel)}"


def test_zapatillas_returns_pla_unit_products():
    """parse_serp on zapatillas fixture yields 30+ pla-units across diverse stores."""
    cands = parse_serp(_load("pla_unit_zapatillas.html"))
    pla = [c for c in cands if "pla_unit" in (c.get("flags") or [])]
    real_url = [c for c in pla if c.get("url") and "google.com" not in c["url"]]
    assert len(real_url) >= 30, f"Expected >=30 real-URL pla, got {len(real_url)}"
    # Stores diversos (sponsoreados de retail AR — sporting, nike, stockcenter, etc.)
    stores = {c["store_hint"] for c in pla if c.get("store_hint")}
    assert len(stores) >= 3, f"Store diversity check: {stores}"


def test_robotech_no_duplicate_urls_within_pla_block():
    """Internal dedupe: si Google duplica una URL en panel + carousel paralelo,
    el pass de pla-unit dedupea internamente. Verifica que NO hay URLs duplicadas
    entre los candidates con flag pla_unit."""
    cands = parse_serp(_load("pla_unit_robotech.html"))
    pla = [c for c in cands if "pla_unit" in (c.get("flags") or [])]
    urls = [c["url"] for c in pla]
    assert len(urls) == len(set(urls)), f"Duplicate URLs within pla block: {urls}"


def test_price_regex_no_dirty_prices_in_robotech():
    """No more $410.420,311001 in any candidate. All AR prices must end in ,DD
    (thousands form) or be a plain integer (legacy ARS/U$S format).
    Regression test for PARITY-03 bug fix.
    """
    cands = parse_serp(_load("pla_unit_robotech.html"))
    # Accept: $X.XXX,XX optionally with NBSP/space prefix, or ARS/U$S 5000
    valid = re.compile(
        r"^\$\s?(?:\xa0)?[1-9]\d{0,2}(?:\.\d{3})*,\d{2}$"
        r"|^(?:ARS|U\$S)\s\d+$"
    )
    for c in cands:
        p = c.get("price_in_card")
        if p:
            assert valid.match(p), f"Dirty price: {p!r} on candidate {c.get('title') or c.get('url')!r}"
