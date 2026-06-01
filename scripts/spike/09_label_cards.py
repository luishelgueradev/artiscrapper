"""
SERP card extractor + interactive labeller + Pydantic validator.

Modes:
  --mode=extract   Parse SERP HTML fixtures, emit CandidateInput JSONL to stdout
  --mode=label     Interactive labelling session (Claude-as-operator per memory feedback_agent_as_uat_operator)
  --mode=validate  AC-5 gate: validate tests/fixtures/llm/labelled.jsonl, exit 0 if all valid + count in [30,50]

Usage:
  python scripts/spike/09_label_cards.py --mode=extract > artifacts/spike/label_candidates_raw.jsonl
  python scripts/spike/09_label_cards.py --mode=label
  python scripts/spike/09_label_cards.py --mode=validate tests/fixtures/llm/labelled.jsonl

D6 invariant: no asyncio here (sync script) — asyncio.run() not needed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from selectolax.parser import HTMLParser

# Add repo root to path for package import
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.spike.labels import CandidateInput, LabelledCandidate

SERP_DIR = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "serp"
LABELLED_PATH = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "llm" / "labelled.jsonl"
RAW_PATH = Path(__file__).parent.parent.parent / "artifacts" / "spike" / "label_candidates_raw.jsonl"

# AR price format: $ 1.234,56 or $1.234 or $ 8.500
PRICE_RE = re.compile(r'\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)')

# Heuristics for Claude-as-operator auto-labelling
JUNK_HOSTS = {
    "youtube.com", "youtu.be", "wikipedia.org", "es.wikipedia.org",
    "facebook.com", "twitter.com", "instagram.com", "fandom.com",
    "wikia.com", "reddit.com", "tiktok.com", "pinterest.com",
    "ebay.com", "ar.ebay.com", "bo.ebay.com",  # eBay is not an AR product source
}

MARKETPLACE_HOSTS = {
    "mercadolibre.com.ar", "listado.mercadolibre.com.ar",
    "articulo.mercadolibre.com.ar", "mercadoshops.com.ar",
}

BLOG_PATTERNS = re.compile(
    r'\b(blog|noticias|how.?to|guia|tutorial|consejos|revista|magazine|opinion)\b',
    re.IGNORECASE,
)


# ── Extract mode ─────────────────────────────────────────────────────────────

def extract_cards_from_html(html_path: Path, fixture_index: int) -> list[dict]:
    """Parse a SERP HTML and extract CandidateInput-shaped dicts."""
    html = html_path.read_text(encoding="utf-8", errors="replace")
    tree = HTMLParser(html)
    fixture_name = html_path.name

    cards: list[dict] = []

    # Selector cascade: tF2Cxc → Ez5pwe → MjjYud → h3-anchored (D4)
    # Use tF2Cxc as primary (organic results)
    elements = tree.css("div.tF2Cxc")
    cascade_used = "tF2Cxc"

    if not elements:
        elements = tree.css("div.Ez5pwe")
        cascade_used = "Ez5pwe"

    if not elements:
        # MjjYud is a container; h3 within it
        elements = tree.css("div.MjjYud h3")
        cascade_used = "MjjYud>h3"

    if not elements:
        elements = tree.css("h3")
        cascade_used = "h3"

    for card_idx, el in enumerate(elements, start=1):
        # Title
        if cascade_used in ("h3", "MjjYud>h3"):
            h3_el = el
        else:
            h3_el = el.css_first("h3")
        title = h3_el.text(strip=True) if h3_el else ""
        if not title:
            continue

        # URL — first <a href> that's not a Google redirect
        if cascade_used in ("h3", "MjjYud>h3"):
            # el is h3 itself; parent may have the link
            link = None
            for parent_candidate in [el.parent, el.parent.parent if el.parent else None]:
                if parent_candidate:
                    link = parent_candidate.css_first("a[href]")
                    if link:
                        break
        else:
            link = el.css_first("a[href]")
        url = ""
        if link:
            href = link.attributes.get("href", "")
            if href.startswith("/url?") or href.startswith("http"):
                # Strip Google redirect
                if href.startswith("/url?"):
                    m = re.search(r'[?&]url=([^&]+)', href)
                    if m:
                        import urllib.parse
                        url = urllib.parse.unquote(m.group(1))
                    else:
                        url = href
                else:
                    url = href
            elif href.startswith("http"):
                url = href

        if not url:
            continue  # skip cards without a URL

        # Snippet
        snip_el = (
            el.css_first("div.VwiC3b")
            or el.css_first(".st")
            or el.css_first("span.aCOpRe")
            or el.css_first("div[data-snc]")
            or el.css_first(".IsZvec")
        )
        snippet = snip_el.text(strip=True) if snip_el else None
        if snippet and len(snippet) > 300:
            snippet = snippet[:300]

        # Price in card
        card_text = el.text()
        price_match = PRICE_RE.search(card_text)
        price_in_card = price_match.group(0) if price_match else None

        record_id = f"serp{fixture_index:02d}-card{card_idx:02d}"
        card = {
            "id": record_id,
            "source_fixture": fixture_name,
            "cascade_used": cascade_used,
            "candidate": {
                "title": title,
                "url": url,
                "snippet": snippet,
                "price_in_card": price_in_card,
            },
        }
        cards.append(card)

    return cards


def run_extract() -> None:
    """Extract cards from all SERP fixtures and write to stdout."""
    html_files = sorted(SERP_DIR.glob("*.html"))
    if not html_files:
        print(f"ERROR: No HTML files found in {SERP_DIR}", file=sys.stderr)
        sys.exit(1)

    total = 0
    for fixture_idx, html_path in enumerate(html_files, start=1):
        cards = extract_cards_from_html(html_path, fixture_idx)
        for card in cards:
            print(json.dumps(card, ensure_ascii=False))
            total += 1

    print(f"# Extracted {total} cards from {len(html_files)} fixtures", file=sys.stderr)


# ── Label mode ───────────────────────────────────────────────────────────────

def _host_from_url(url: str) -> str:
    """Extract hostname from URL."""
    m = re.match(r'https?://([^/]+)', url)
    return m.group(1).lstrip("www.") if m else ""


def _auto_label(card: dict) -> dict | None:
    """
    Claude-as-operator heuristic labelling (per memory feedback_agent_as_uat_operator).

    Returns a LabelledCandidate-shaped dict, or None to skip.
    """
    candidate = card["candidate"]
    title = candidate["title"]
    url = candidate["url"]
    snippet = candidate.get("snippet") or ""
    price_str = candidate.get("price_in_card")
    host = _host_from_url(url)

    # Social media / junk hosts → label as NOT product (negative example for LLM)
    for junk in JUNK_HOSTS:
        if junk in host:
            return {
                "id": card["id"],
                "source_fixture": card["source_fixture"],
                "candidate": candidate,
                "expected_is_product": False,
                "expected_confidence_min": 0.90,
                "expected_store_hint": None,
                "expected_freshness_signal": "unknown",
                "expected_price_hint": None,
                "notes": f"Red social / junk host: {host} — no es producto",
            }

    # Determine is_product
    has_price = price_str is not None

    # Freshness signal
    is_meli = any(mh in host for mh in MARKETPLACE_HOSTS)
    is_marketplace = is_meli or any(
        kw in host for kw in ["tiendanube", "mitiendanube", "shopify", "myshopify", "walmart"]
    )
    is_blog = bool(BLOG_PATTERNS.search(title)) or bool(BLOG_PATTERNS.search(snippet))
    is_ecommerce = any(
        kw in host for kw in [
            ".com.ar", ".ar", "shop", "store", "repuesto", "auto", "freno", "aceite",
            "filtro", "bujia", "corona", "jirsa", "sacpa", "palermo",
        ]
    )

    if is_blog:
        expected_is_product = False
        expected_confidence_min = 0.85
        expected_freshness_signal = "blog"
        expected_store_hint = None
        expected_price_hint = None
        notes = "Detectado como blog/artículo informativo"
    elif is_meli:
        expected_is_product = True
        expected_confidence_min = 0.85
        expected_freshness_signal = "live_marketplace"
        expected_store_hint = "MercadoLibre"
        expected_price_hint = _parse_price(price_str) if price_str else None
        notes = "MELI listing — live_marketplace"
    elif has_price and is_ecommerce:
        expected_is_product = True
        expected_confidence_min = 0.80
        expected_freshness_signal = "static_catalog" if not is_marketplace else "live_marketplace"
        expected_store_hint = host.split(".")[0].capitalize() if host else None
        expected_price_hint = _parse_price(price_str)
        notes = "E-commerce con precio en SERP"
    elif is_marketplace:
        expected_is_product = True
        expected_confidence_min = 0.75
        expected_freshness_signal = "live_marketplace"
        expected_store_hint = host.split(".")[0].capitalize()
        expected_price_hint = _parse_price(price_str) if price_str else None
        notes = "Marketplace listing"
    elif not has_price and not is_ecommerce:
        # Ambiguous — could be product page or info page
        if any(kw in title.lower() for kw in ["comprar", "precio", "repuesto", "filtro", "aceite", "freno", "bujia", "amortiguador", "balata", "correa", "kit", "pelota"]):
            expected_is_product = True
            expected_confidence_min = 0.65
            expected_freshness_signal = "static_catalog"
            expected_store_hint = host.split(".")[0].capitalize() if host else None
            expected_price_hint = None
            notes = "Probable producto sin precio en SERP"
        else:
            expected_is_product = False
            expected_confidence_min = 0.70
            expected_freshness_signal = "unknown"
            expected_store_hint = None
            expected_price_hint = None
            notes = "Ambiguo — sin precio, sin señal de tienda"
    else:
        expected_is_product = True
        expected_confidence_min = 0.70
        expected_freshness_signal = "static_catalog"
        expected_store_hint = host.split(".")[0].capitalize() if host else None
        expected_price_hint = None
        notes = "E-commerce sin precio explícito en SERP"

    return {
        "id": card["id"],
        "source_fixture": card["source_fixture"],
        "candidate": candidate,
        "expected_is_product": expected_is_product,
        "expected_confidence_min": expected_confidence_min,
        "expected_store_hint": expected_store_hint,
        "expected_freshness_signal": expected_freshness_signal,
        "expected_price_hint": expected_price_hint,
        "notes": notes,
    }


def _parse_price(price_str: str | None) -> float | None:
    """Parse AR price string like '$ 8.500' or '$ 12.501,15' to float."""
    if not price_str:
        return None
    # Remove $ and spaces
    s = re.sub(r'[\$\s]', '', price_str)
    # AR format: thousands separator = ".", decimal separator = ","
    # Remove thousands dots: 1.234.567 → 1234567
    s = re.sub(r'\.(?=\d{3})', '', s)
    # Replace decimal comma: 12.501,15 → 12501.15
    s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None


def run_label() -> None:
    """
    Auto-label mode (Claude-as-operator per memory feedback_agent_as_uat_operator).

    Reads artifacts/spike/label_candidates_raw.jsonl, applies heuristics,
    writes 30-50 validated records to tests/fixtures/llm/labelled.jsonl.
    """
    if not RAW_PATH.exists():
        print(f"ERROR: {RAW_PATH} not found. Run --mode=extract first.", file=sys.stderr)
        sys.exit(1)

    LABELLED_PATH.parent.mkdir(parents=True, exist_ok=True)

    raw_cards = []
    for line in RAW_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        raw_cards.append(json.loads(line))

    labelled_records: list[str] = []
    skipped = 0

    for card in raw_cards:
        if len(labelled_records) >= 50:
            break

        labelled = _auto_label(card)
        if labelled is None:
            skipped += 1
            continue

        # Validate with Pydantic
        try:
            validated = LabelledCandidate.model_validate(labelled)
        except Exception as e:
            print(f"SKIP {card['id']}: validation error: {e}", file=sys.stderr)
            skipped += 1
            continue

        labelled_records.append(validated.model_dump_json())

        if len(labelled_records) == 30:
            print(f"INFO: AC-5 minimum reached (30 records). Continuing to 50...", file=sys.stderr)

    if len(labelled_records) < 30:
        print(
            f"WARNING: Only {len(labelled_records)} records labelled (minimum 30 required). "
            f"Skipped {skipped} records. Check heuristics.",
            file=sys.stderr,
        )

    # Write labelled.jsonl
    LABELLED_PATH.write_text("\n".join(labelled_records) + "\n")
    print(
        f"Labelled {len(labelled_records)} records → {LABELLED_PATH} "
        f"(skipped {skipped})",
        file=sys.stderr,
    )

    # Quick distribution summary
    positives = sum(1 for l in labelled_records if '"expected_is_product":true' in l)
    negatives = sum(1 for l in labelled_records if '"expected_is_product":false' in l)
    print(
        f"Distribution: {positives} positive, {negatives} negative, "
        f"{len(labelled_records) - positives - negatives} ambiguous",
        file=sys.stderr,
    )


# ── Validate mode ────────────────────────────────────────────────────────────

def run_validate(jsonl_path_str: str) -> None:
    """AC-5 gate: validate labelled.jsonl. Exit 0 if valid + count in [30,50]."""
    jsonl_path = Path(jsonl_path_str)
    if not jsonl_path.exists():
        print(f"LABELLED_VALID: NO (file not found: {jsonl_path})")
        sys.exit(1)

    lines = [l.strip() for l in jsonl_path.read_text().splitlines() if l.strip()]
    count = len(lines)
    print(f"LABELLED_COUNT: {count}")

    for line_no, line in enumerate(lines, start=1):
        try:
            LabelledCandidate.model_validate_json(line)
        except Exception as e:
            print(f"LABELLED_VALID: NO (first failure at line {line_no}: {e})")
            sys.exit(1)

    if count < 30:
        print(f"LABELLED_VALID: NO (count={count} < 30)")
        sys.exit(1)

    if count > 50:
        print(f"LABELLED_VALID: NO (count={count} > 50)")
        sys.exit(1)

    print("LABELLED_VALID: YES")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="SERP card extractor + labeller + validator")
    parser.add_argument(
        "--mode",
        choices=["extract", "label", "validate"],
        default="extract",
        help="Mode of operation",
    )
    parser.add_argument(
        "jsonl_path",
        nargs="?",
        default=str(LABELLED_PATH),
        help="Path to JSONL file for validate mode",
    )
    args = parser.parse_args()

    if args.mode == "extract":
        run_extract()
    elif args.mode == "label":
        run_label()
    elif args.mode == "validate":
        run_validate(args.jsonl_path)


if __name__ == "__main__":
    main()
