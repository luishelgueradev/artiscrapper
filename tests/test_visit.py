"""
Visit pass tests — plan 02-02 Wave 2.
VISIT-01..08 requirements.
"""

import pathlib

import httpx
import respx
from selectolax.parser import HTMLParser

from src.artiscrapper.visit import (
    AR_PRICE_PATTERN,
    classify_response,
    extract_jsonld_product,
    extract_product,
    visit_candidates,
)

# ──────────────────────────────────────────
# VISIT-05: classify_response
# ──────────────────────────────────────────


def test_classify_soft404():
    """VISIT-05: classify_response returns 'dead' for redirect-to-home soft-404."""
    # Simulate a response with no request set — URL defaults to "" which normalizes to "/"
    # hitting SOFT_404_PATHS → "dead"
    mock_resp = httpx.Response(
        200,
        content=b"<html><body><h1>Home</h1></body></html>",
        headers={"content-type": "text/html"},
    )
    # No request set → URL access raises RuntimeError → path = "" → in SOFT_404_PATHS → "dead"
    result = classify_response(mock_resp)
    assert result == "dead"


def test_classify_soft404_path():
    """VISIT-05: classify_response returns 'dead' for response redirected to /."""
    # Create response with explicit request URL "https://store.com/" (root path)
    large_body = b"<html><body>" + b"x" * 5001 + b"</body></html>"
    request = httpx.Request("GET", "https://store.com/")
    mock_resp = httpx.Response(
        200,
        content=large_body,
        headers={"content-type": "text/html; charset=utf-8"},
        request=request,
    )
    result = classify_response(mock_resp)
    assert result == "dead"


def test_classify_4xx():
    """VISIT-05: classify_response returns 'failed' for 4xx responses."""
    request = httpx.Request("GET", "https://store.com/product/123")
    resp = httpx.Response(
        404, content=b"Not Found", headers={"content-type": "text/html"}, request=request
    )
    assert classify_response(resp) == "failed"


def test_classify_500():
    """VISIT-05: classify_response returns 'failed' for 5xx responses."""
    request = httpx.Request("GET", "https://store.com/product/123")
    resp = httpx.Response(
        503, content=b"Service Unavailable", headers={"content-type": "text/html"}, request=request
    )
    assert classify_response(resp) == "failed"


# ──────────────────────────────────────────
# VISIT-06: extractor cascade
# ──────────────────────────────────────────


def test_extractor_catalog_fixtures():
    """
    VISIT-06: extract_jsonld_product extracts Product from 9 jsonld-sufficient catalog fixtures.
    D12: 9/10 fixtures are jsonld-sufficient per MANIFEST.md (falabella is regex-fallback).
    """
    catalog_dir = pathlib.Path(__file__).parent / "fixtures" / "catalog"
    # Falabella is regex-fallback per SPIKE.md; the other 9 are jsonld-sufficient
    jsonld_hosts = [
        "argautopartes_com_ar",
        "autodo_com_ar",
        "casasusy_com_ar",
        "dphidraulica_com_ar",
        "lspalermo_com_ar",
        "martinmorris_ar",
        "mayoristafrog_com_ar",
        "mipol_com_ar",
        "reps_com_ar",
    ]
    for host in jsonld_hosts:
        fixture = catalog_dir / host / "product-01.html"
        assert fixture.exists(), f"Fixture missing: {fixture}"
        html = fixture.read_text(encoding="utf-8", errors="replace")
        tree = HTMLParser(html)
        result = extract_jsonld_product(tree)
        assert result is not None, f"extract_jsonld_product returned None for {host}"


def test_extractor_full_cascade_has_price():
    """
    VISIT-06: extract_product (full cascade) returns non-None price for all 9 jsonld fixtures.
    Uses the full cascade that also checks OG and priceSpecification.
    """
    catalog_dir = pathlib.Path(__file__).parent / "fixtures" / "catalog"
    jsonld_hosts = [
        "argautopartes_com_ar",
        "autodo_com_ar",
        "casasusy_com_ar",
        "dphidraulica_com_ar",
        "lspalermo_com_ar",
        "martinmorris_ar",
        "mayoristafrog_com_ar",
        "mipol_com_ar",
        "reps_com_ar",
    ]
    for host in jsonld_hosts:
        fixture = catalog_dir / host / "product-01.html"
        html = fixture.read_text(encoding="utf-8", errors="replace")
        result = extract_product(html)
        assert result is not None, f"extract_product returned None for {host}"
        assert result.get("price") is not None, (
            f"extract_product returned None price for {host}: {result}"
        )


def test_ar_price_regex():
    """VISIT-06: AR price regex matches ARS/$/ pesos formats."""
    samples = [
        "$ 18.032",
        "ARS 18.032,30",
        "$29.990",
        "$ 18.032,30",
        "$5.000",
        "ARS 24.900",
    ]
    for text in samples:
        m = AR_PRICE_PATTERN.search(text)
        assert m is not None, f"AR_PRICE_PATTERN did not match: {text!r}"


def test_ar_price_regex_pesos():
    """VISIT-06: AR price regex matches 'pesos' format."""
    m = AR_PRICE_PATTERN.search("pesos 5000")
    assert m is not None, "AR_PRICE_PATTERN should match 'pesos 5000'"
    m2 = AR_PRICE_PATTERN.search("pesos $5.000")
    assert m2 is not None, "AR_PRICE_PATTERN should match 'pesos $5.000'"


# ──────────────────────────────────────────
# VISIT-08: MELI guard
# ──────────────────────────────────────────


async def test_meli_guard():
    """VISIT-08: MELI host guard fires on any *.mercadolibre.* URL without HTTP call."""
    meli_url = "https://www.mercadolibre.com.ar/MLA-123456-filtro-aceite-_JM"
    candidate = {"url": meli_url, "title": "Filtro MELI", "flags": []}

    # Use respx to intercept any HTTP calls — should see zero requests
    with respx.mock:
        results = await visit_candidates([candidate])

    assert len(results) == 1
    assert "meli_skip" in results[0].get("flags", []), (
        "VISIT-08: meli_skip flag should be set for mercadolibre.* URLs"
    )


async def test_meli_guard_no_http():
    """VISIT-08: MELI guard returns immediately — no HTTP calls are made."""
    meli_url = "https://articulo.mercadolibre.com.ar/MLA-999-test"
    candidate = {"url": meli_url, "title": "Test", "flags": []}

    with respx.mock:
        # If any HTTP call is attempted, respx will raise (no routes defined)
        results = await visit_candidates([candidate])

    assert "meli_skip" in results[0].get("flags", [])


async def test_skip_if_price_present():
    """VISIT-01: skip-if-you-can — no visit when price is already known."""
    candidate = {
        "url": "https://argautopartes.com.ar/prod/1",
        "title": "Filtro",
        "price": "18032",
        "flags": [],
    }
    # No HTTP calls should be made (price is set)
    with respx.mock:
        results = await visit_candidates([candidate])

    # Candidate returned as-is with price preserved
    assert results[0]["price"] == "18032"
    assert "meli_skip" not in results[0].get("flags", [])
