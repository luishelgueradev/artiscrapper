"""
D12 ≥85% catalog price extraction test (Phase 3 — Plan 03-02, ROADMAP-6).

In-process sweep of every Phase 1 catalog HTML fixture through
`src.artiscrapper.visit.extract_product()`. Counts the fixtures that
yield a non-empty `price` and asserts the aggregate rate ≥ 85%.

D-18 alignment: builds a per-fixture `(filename, has_price, price)`
tuple list so a regression message points at the SPECIFIC host that
broke — never a bare `len > 0`.

This is the production-gate validation of D12: Phase 1 SPIKE measured
9/10 jsonld-sufficient empirically; this test pins that bar across
all subsequent fixture rotations.
"""

import pathlib

import pytest

from src.artiscrapper.visit import extract_product

CATALOG_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "catalog"


@pytest.mark.integration
def test_catalog_price_extraction_rate_above_85_percent():
    """
    ROADMAP-6 / D12: ≥85% of Phase 1 catalog fixtures yield a price via
    `extract_product` (in-process — no HTTP, no LLM).

    Per-fixture details list is included in the failure message so a
    regression points at the EXACT host that started returning None or
    an empty `price` key.
    """
    fixture_files: list[pathlib.Path] = []
    for host_dir in sorted(CATALOG_DIR.iterdir()):
        if not host_dir.is_dir():
            continue
        fixture_files.extend(sorted(host_dir.glob("*.html")))

    assert len(fixture_files) >= 10, (
        f"Expected ≥10 catalog fixtures (Phase 1 spike captured 10); "
        f"found {len(fixture_files)}. Was the fixture set deleted/moved?"
    )

    with_price = 0
    details: list[tuple[str, bool, object]] = []
    for fpath in fixture_files:
        html = fpath.read_text(encoding="utf-8", errors="replace")
        extracted = extract_product(html)
        price_val = None
        has_price = False
        if extracted is not None:
            price_val = extracted.get("price")
            has_price = bool(price_val)
        # Use host_slug/file shape for forensic clarity.
        rel = f"{fpath.parent.name}/{fpath.name}"
        details.append((rel, has_price, price_val))
        if has_price:
            with_price += 1

    rate = with_price / len(fixture_files)
    assert rate >= 0.85, (
        f"D12 catalog price extraction rate regressed to {rate:.2%} "
        f"(got {with_price}/{len(fixture_files)} fixtures with price). "
        f"Acceptance bar is ≥85%. Per-fixture details: {details}"
    )
