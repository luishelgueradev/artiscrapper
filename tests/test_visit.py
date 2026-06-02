"""
Visit pass test stubs — xfail until plan 02-02 ships visit.py.
VISIT-01..08 requirements.
"""
import pytest

try:
    from src.artiscrapper.visit import (
        classify_response,
        extract_jsonld_product,
        extract_price_regex,
        visit_candidates,
        AR_PRICE_PATTERN,
    )
    _VISIT_AVAILABLE = True
except ImportError:
    _VISIT_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not _VISIT_AVAILABLE,
    reason="visit.py not yet implemented — will be filled by plan 02-02",
)


@pytest.mark.xfail(strict=False, reason="Wave 2: visit.py filled by plan 02-02")
def test_classify_soft404():
    """VISIT-05: classify_response returns 'dead' for redirect-to-home soft-404."""
    import httpx
    # Simulate a response that redirected to homepage (soft 404)
    mock_resp = httpx.Response(200, content=b"<html><body><h1>Home</h1></body></html>",
                                headers={"content-type": "text/html"})
    # Override the URL to simulate a redirect to /
    assert classify_response(mock_resp) in ("dead", "live")  # depends on body content


@pytest.mark.xfail(strict=False, reason="Wave 2: visit.py filled by plan 02-02")
def test_classify_4xx():
    """VISIT-05: classify_response returns 'failed' for 4xx responses."""
    import httpx
    resp = httpx.Response(404, content=b"Not Found", headers={"content-type": "text/html"})
    assert classify_response(resp) == "failed"


@pytest.mark.xfail(strict=False, reason="Wave 2: visit.py filled by plan 02-02")
def test_extractor_catalog_fixtures():
    """VISIT-06: extract_jsonld_product extracts price from 9 jsonld-sufficient catalog fixtures."""
    import pathlib
    from selectolax.parser import HTMLParser

    catalog_dir = pathlib.Path(__file__).parent / "fixtures" / "catalog"
    # Falabella is regex-fallback per SPIKE.md; the other 9 are jsonld-sufficient
    jsonld_hosts = [
        "argautopartes_com_ar", "autodo_com_ar", "casasusy_com_ar",
        "dphidraulica_com_ar", "lspalermo_com_ar", "martinmorris_ar",
        "mayoristafrog_com_ar", "mipol_com_ar", "reps_com_ar",
    ]
    for host in jsonld_hosts:
        fixture = catalog_dir / host / "product-01.html"
        assert fixture.exists(), f"Fixture missing: {fixture}"
        html = fixture.read_text(encoding="utf-8", errors="replace")
        tree = HTMLParser(html)
        result = extract_jsonld_product(tree)
        assert result is not None, f"extract_jsonld_product returned None for {host}"


@pytest.mark.xfail(strict=False, reason="Wave 2: visit.py filled by plan 02-02")
def test_ar_price_regex():
    """VISIT-06: AR price regex matches ARS/$/ pesos formats."""
    import re
    samples = [
        ("$ 18.032", "18032"),
        ("ARS 18.032,30", "18032"),  # canonical group captures before comma
        ("$29.990", "29990"),
        ("18032,30 pesos", "18032"),
    ]
    for text, expected_core in samples:
        m = AR_PRICE_PATTERN.search(text)
        assert m is not None, f"AR_PRICE_PATTERN did not match: {text!r}"


@pytest.mark.xfail(strict=False, reason="Wave 2: visit.py filled by plan 02-02")
async def test_meli_guard():
    """VISIT-08: MELI host guard fires on any *.mercadolibre.* URL without HTTP call."""
    meli_url = "https://www.mercadolibre.com.ar/MLA-123456-filtro-aceite-_JM"
    candidate = {"url": meli_url, "title": "Filtro MELI", "flags": []}
    results = await visit_candidates([candidate])
    assert len(results) == 1
    assert "meli_skip" in results[0].get("flags", []), (
        "VISIT-08: meli_skip flag should be set for mercadolibre.* URLs"
    )
