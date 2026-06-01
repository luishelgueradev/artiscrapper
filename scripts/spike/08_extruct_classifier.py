#!/usr/bin/env python3
"""
08_extruct_classifier.py — Hand-rolled catalog fixture classifier (D12 gate).

This script decides whether to ADOPT extruct or KEEP the hand-rolled selectolax extractor.
The extruct library is deliberately NOT imported — the script's whole point is to test
whether the hand-rolled approach is sufficient.

Loads each catalog fixture under tests/fixtures/catalog/**/*.html, runs the hand-rolled
JSON-LD + OG + microdata + regex extractor (verbatim from RESEARCH §Pattern 5 lines 540-597),
classifies each into one of 5 tiers, and applies the D12 decision rule.

References:
  01-RESEARCH.md §Pattern 5 (lines 540-597) — VERBATIM extractor functions
  01-RESEARCH.md D12 decision rule (lines 614-617) — ≥8/10 → HAND-ROLL stays
  01-03-PLAN.md Task 3 — acceptance criteria

Output files:
  artifacts/spike/classifier_results.txt — per-fixture classification table + aggregate
  artifacts/spike/d12_decision.txt — D12_DECISION: HAND-ROLL | EXTRUCT | NEEDS-PIVOT-MORE-SAMPLES

D12 decision rules (RESEARCH lines 614-617 VERBATIM):
  - ≥8/10 fixtures jsonld-sufficient OR og-only → HAND-ROLL (D12 stays locked)
  - 3+ fixtures microdata-only OR blob-JS-only → EXTRUCT (D12 flips)
  - Borderline (4-7/10 sufficient) → NEEDS-PIVOT-MORE-SAMPLES (D12 flips conservatively)

The name "extruct_classifier" reflects what this script DECIDES about extruct, not what it uses.

Exit codes:
  0 — classification and D12 decision completed
  1 — no fixtures found or fatal error
"""

import json
import re
import sys
from pathlib import Path

# ── selectolax import ─────────────────────────────────────────────────────────
try:
    from selectolax.parser import HTMLParser
except ImportError:
    print("ERROR: selectolax not installed — run: uv pip install selectolax==0.4.10", file=sys.stderr)
    sys.exit(1)

FIXTURES_DIR = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "catalog"
ARTIFACTS_DIR = Path(__file__).parent.parent.parent / "artifacts" / "spike"
MANIFEST_FILE = FIXTURES_DIR / "MANIFEST.md"
RESULTS_FILE = ARTIFACTS_DIR / "classifier_results.txt"
DECISION_FILE = ARTIFACTS_DIR / "d12_decision.txt"

# ── VERBATIM extractor functions from RESEARCH §Pattern 5 (lines 540-597) ────


def extract_jsonld_product(tree: HTMLParser) -> dict | None:
    for script in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text())
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        # flatten @graph wrappers
        flat = []
        for it in items:
            if isinstance(it, dict) and "@graph" in it:
                flat.extend(it["@graph"])
            else:
                flat.append(it)
        for it in flat:
            if not isinstance(it, dict):
                continue
            t = it.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                return it
    return None


def extract_og_product(tree: HTMLParser) -> dict | None:
    metas = {}
    for m in tree.css("meta[property]"):
        prop = m.attributes.get("property")
        content = m.attributes.get("content")
        if prop and content:
            metas[prop] = content
    if "product:price:amount" in metas:
        return {
            "price": metas["product:price:amount"],
            "currency": metas.get("product:price:currency", "ARS"),
            "name": metas.get("og:title"),
            "image": metas.get("og:image"),
        }
    return None


def extract_microdata_product(tree: HTMLParser) -> dict | None:
    root = tree.css_first("[itemtype$='/Product']")
    if root is None:
        return None
    out = {}
    for el in root.css("[itemprop]"):
        prop = el.attributes.get("itemprop")
        val = el.attributes.get("content") or el.text(strip=True)
        if prop and val and prop not in out:
            out[prop] = val
    return out or None


def classify(html: str) -> tuple[str, dict | None]:
    tree = HTMLParser(html)
    jsonld = extract_jsonld_product(tree)
    og = extract_og_product(tree)
    micro = extract_microdata_product(tree)
    if jsonld and jsonld.get("offers"):
        return ("jsonld-sufficient", jsonld)
    if og and og.get("price"):
        return ("og-only", og)
    if micro and micro.get("price"):
        return ("microdata-only", micro)
    # Last resort: regex over text body looking for AR price
    # AR price regex — VERBATIM from RESEARCH line 595
    m = re.search(r'\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)', html)
    if m:
        return ("regex-fallback", {"price_text": m.group(0)})
    return ("blob-JS-only", None)


# ── Helper: extract name and price from classified data ──────────────────────

def extract_name(tier: str, data: dict | None) -> str:
    if data is None:
        return "(none)"
    if tier == "jsonld-sufficient":
        return (data.get("name") or "(no name)")[:60]
    if tier == "og-only":
        return (data.get("name") or "(no name)")[:60]
    if tier == "microdata-only":
        return (data.get("name") or "(no name)")[:60]
    return "(none)"


def extract_price(tier: str, data: dict | None) -> str:
    if data is None:
        return "(none)"
    if tier == "jsonld-sufficient":
        offers = data.get("offers")
        if isinstance(offers, dict):
            price = offers.get("price") or offers.get("lowPrice")
            currency = offers.get("priceCurrency", "ARS")
            if price:
                return f"{currency} {price}"
        elif isinstance(offers, list) and offers:
            price = offers[0].get("price") or offers[0].get("lowPrice")
            currency = offers[0].get("priceCurrency", "ARS")
            if price:
                return f"{currency} {price}"
        return "(offers present, price not extracted)"
    if tier == "og-only":
        price = data.get("price")
        currency = data.get("currency", "ARS")
        return f"{currency} {price}" if price else "(none)"
    if tier == "microdata-only":
        return data.get("price", "(none)")[:40]
    if tier == "regex-fallback":
        return data.get("price_text", "(none)")
    return "(none)"


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    # Collect all fixture HTML files
    fixtures = sorted(FIXTURES_DIR.glob("**/*.html"))
    if not fixtures:
        print(f"ERROR: no .html fixtures found under {FIXTURES_DIR}", file=sys.stderr)
        print("Run task 1 (06_capture_catalog.py) first.", file=sys.stderr)
        return 1

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Per-fixture classification ─────────────────────────────────────────
    rows = []
    tier_counts = {
        "jsonld-sufficient": 0,
        "og-only": 0,
        "microdata-only": 0,
        "regex-fallback": 0,
        "blob-JS-only": 0,
    }

    print(f"Classifying {len(fixtures)} fixtures...")
    print()

    for fixture_path in fixtures:
        host_slug = fixture_path.parent.name
        filename = fixture_path.name
        try:
            html = fixture_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"  ERROR reading {fixture_path}: {e}", file=sys.stderr)
            continue

        tier, data = classify(html)
        tier_counts[tier] += 1

        name = extract_name(tier, data)
        price = extract_price(tier, data)

        row = {
            "host_slug": host_slug,
            "filename": filename,
            "tier": tier,
            "extracted_price": price,
            "extracted_name": name,
        }
        rows.append(row)

        # Print to stdout for operator visibility
        print(f"  {host_slug:<30} {filename:<20} {tier:<22} {price[:20]:<22} {name[:40]}")

    # ── Write classifier_results.txt ──────────────────────────────────────
    sufficient_count = tier_counts["jsonld-sufficient"] + tier_counts["og-only"]
    total = len(rows)

    result_lines = []
    result_lines.append("# Catalog Fixture Classification Results")
    result_lines.append("# Generated by scripts/spike/08_extruct_classifier.py")
    result_lines.append("")
    result_lines.append(f"{'host_slug':<30} | {'fixture_filename':<20} | {'classification':<22} | {'extracted_price':<22} | extracted_name")
    result_lines.append(f"{'---':<30} | {'---':<20} | {'---':<22} | {'---':<22} | ---")
    for r in rows:
        result_lines.append(
            f"{r['host_slug']:<30} | {r['filename']:<20} | {r['tier']:<22} | {r['extracted_price'][:22]:<22} | {r['extracted_name'][:60]}"
        )
    result_lines.append("")
    result_lines.append("## Aggregate")
    result_lines.append(f"total_fixtures: {total}")
    result_lines.append(f"jsonld-sufficient: {tier_counts['jsonld-sufficient']}")
    result_lines.append(f"og-only: {tier_counts['og-only']}")
    result_lines.append(f"microdata-only: {tier_counts['microdata-only']}")
    result_lines.append(f"regex-fallback: {tier_counts['regex-fallback']}")
    result_lines.append(f"blob-JS-only: {tier_counts['blob-JS-only']}")
    result_lines.append(f"sufficient_count (jsonld+og): {sufficient_count}")

    RESULTS_FILE.write_text("\n".join(result_lines) + "\n", encoding="utf-8")
    print(f"\nWritten: {RESULTS_FILE}")

    # ── D12 decision rule (RESEARCH lines 614-617 VERBATIM) ──────────────
    needs_extruct_count = tier_counts["microdata-only"] + tier_counts["blob-JS-only"]

    if sufficient_count >= 8:
        decision = "HAND-ROLL"
        rationale = (
            f"{sufficient_count}/10 fixtures classified as jsonld-sufficient or og-only "
            f"(threshold ≥8). Hand-rolled selectolax extractor covers the AR catalog surface. "
            f"Phase 2 plan 02-02 ships hand-rolled VISIT-06 unchanged."
        )
    elif needs_extruct_count >= 3:
        decision = "EXTRUCT"
        rationale = (
            f"{needs_extruct_count}/10 fixtures classified as microdata-only or blob-JS-only "
            f"(threshold ≥3). Hand-rolled approach insufficient. Phase 2 plan 02-02 must add "
            f"extruct==0.18.0 to pyproject.toml and update VISIT-06 acceptance."
        )
    else:
        decision = "NEEDS-PIVOT-MORE-SAMPLES"
        rationale = (
            f"Borderline: {sufficient_count}/10 sufficient (threshold ≥8), "
            f"{needs_extruct_count}/10 needing extruct (threshold ≥3). "
            f"D12 flips conservatively. Phase 2 plan 02-02 adds extruct as a hedge AND a task "
            f"to revisit with 10 more fixtures post-MVP."
        )

    decision_lines = []
    decision_lines.append(f"D12_DECISION: {decision}")
    decision_lines.append("")
    decision_lines.append(f"# Rationale")
    decision_lines.append(rationale)
    decision_lines.append("")
    decision_lines.append(f"# Aggregate counts")
    decision_lines.append(f"sufficient (jsonld+og): {sufficient_count}/10")
    decision_lines.append(f"needs-extruct (microdata+blob): {needs_extruct_count}/10")
    decision_lines.append(f"jsonld-sufficient: {tier_counts['jsonld-sufficient']}")
    decision_lines.append(f"og-only: {tier_counts['og-only']}")
    decision_lines.append(f"microdata-only: {tier_counts['microdata-only']}")
    decision_lines.append(f"regex-fallback: {tier_counts['regex-fallback']}")
    decision_lines.append(f"blob-JS-only: {tier_counts['blob-JS-only']}")

    if decision == "EXTRUCT":
        decision_lines.append("")
        decision_lines.append("Phase 2 dependency: add extruct==0.18.0 to pyproject.toml")

    DECISION_FILE.write_text("\n".join(decision_lines) + "\n", encoding="utf-8")
    print(f"Written: {DECISION_FILE}")

    print(f"\nD12_DECISION: {decision}")
    print(f"Rationale: {rationale}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
