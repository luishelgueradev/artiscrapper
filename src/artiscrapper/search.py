"""
SERP URL builder + four-level parser cascade + URL canonicalization + dedupe + blocklist + rerank.
Pattern 9 (build_serp_url), §Code Examples (cascade + canonicalize + dedupe + is_junk + rerank)
from 02-RESEARCH.md.
SEARCH-03: pws=0&safe=off (D3). SEARCH-04: parser cascade with alert (D4). SEARCH-05: canonicalize + dedupe.
SEARCH-06: junk-domain blocklist (D9). SEARCH-07: re-rank.
OBS-05: NEVER log title, snippet, url, or reason.
"""

from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

import structlog
from selectolax.parser import HTMLParser

log = structlog.get_logger()


# ──────────────────────────────────────────
# URL building (SEARCH-03 / D3)
# ──────────────────────────────────────────


def build_serp_url(query: str, *, meli: bool = False) -> str:
    """
    D3: pws=0&safe=off always. NO num/tbm/udm/site:.
    URL B appends 'mercadolibre' to the query (NOT site: operator).
    Pattern 9 from 02-RESEARCH.md (lines 1173-1184).
    """
    q = f"{query} mercadolibre" if meli else query
    # quote_via=quote: spaces become %20, not +
    params = urlencode(
        {"q": q, "hl": "es", "gl": "ar", "pws": "0", "safe": "off"},
        quote_via=quote,
    )
    return f"https://www.google.com/search?{params}"


# ──────────────────────────────────────────
# Parser cascade (SEARCH-04 / D4)
# ──────────────────────────────────────────

ORGANIC_SELECTORS = [
    "div.MjjYud div.tF2Cxc",  # 2024-2026 primary (Phase 1 confirmed all 10 SERP fixtures)
    "div.MjjYud",  # 2025+ wrapper fallback
    "div.g",  # legacy
    "div[data-sokoban-container]",  # 2025-2026 experimental
    "div[data-snc]",  # mobile variants
]
CAROUSEL_SELECTORS = [
    "div.Ez5pwe",  # carousel (Phase 1 fixtures confirmed present)
    "g-scrolling-carousel div[role='listitem']",
]


def _extract_organic(node) -> dict | None:
    """Extract a candidate dict from an organic SERP result node."""
    # Find the link
    link = node.css_first("a[href]")
    if link is None:
        return None
    href = link.attributes.get("href", "")
    if not href or not href.startswith("http"):
        return None

    # Title from h3
    h3 = node.css_first("h3")
    title = h3.text(strip=True) if h3 else None

    # Snippet from VwiC3b or similar
    snippet_el = node.css_first("div.VwiC3b") or node.css_first("div[data-snc]")
    snippet = snippet_el.text(strip=True) if snippet_el else None

    # Price hint in card (carousel cards sometimes have price)
    price_in_card = None
    for price_sel in (".price", ".precio", "[aria-label*='precio']", "[aria-label*='price']"):
        price_el = node.css_first(price_sel)
        if price_el:
            price_in_card = price_el.text(strip=True)
            break

    return {
        "url": href,
        "title": title,
        "snippet": snippet,
        "price_in_card": price_in_card,
        "has_price": bool(price_in_card),
        "flags": [],
    }


def _extract_carousel(node) -> dict | None:
    """Extract a candidate dict from a carousel item node."""
    link = node.css_first("a[href]")
    if link is None:
        return None
    href = link.attributes.get("href", "")
    if not href or not href.startswith("http"):
        return None

    title_el = node.css_first("div.title") or node.css_first("span") or node.css_first("h3")
    title = title_el.text(strip=True) if title_el else None

    price_el = (
        node.css_first("span.price") or node.css_first("div.price") or node.css_first(".precio")
    )
    price_in_card = price_el.text(strip=True) if price_el else None

    return {
        "url": href,
        "title": title,
        "snippet": None,
        "price_in_card": price_in_card,
        "has_price": bool(price_in_card),
        "flags": ["carousel"],
    }


def _extract_by_h3(tree: HTMLParser) -> list[dict]:
    """
    h3-anchored fallback extractor — last resort when all organic selectors fail (D4).
    Walks each h3, climbs to nearest <a> parent.
    """
    candidates = []
    for h3 in tree.css("h3"):
        # Look for ancestor <a href>
        node = h3
        link = None
        for _ in range(5):  # climb at most 5 levels
            parent = node.parent
            if parent is None:
                break
            if parent.tag == "a" and parent.attributes.get("href", "").startswith("http"):
                link = parent
                break
            node = parent
        if link is None:
            # Try css_first inside h3's container
            link = h3.parent.css_first("a[href]") if h3.parent else None
        if link is None:
            continue
        href = link.attributes.get("href", "")
        if not href.startswith("http"):
            continue
        candidates.append(
            {
                "url": href,
                "title": h3.text(strip=True),
                "snippet": None,
                "price_in_card": None,
                "has_price": False,
                "flags": ["h3_fallback"],
            }
        )
    return candidates


def parse_serp(html: str) -> list[dict]:
    """
    Four-level parser cascade: tF2Cxc → MjjYud → div.g → sokoban → snc → h3-fallback.
    D4 alert: logs parse_cascade_exhausted when all organic selectors yield 0 results.
    Carousel selectors run independently (separate loop, does not affect organic cascade alert).
    Pattern from 02-RESEARCH.md §Code Examples (lines 1482-1516).
    """
    tree = HTMLParser(html)
    candidates: list[dict] = []

    # Organic cascade (for/else: else fires when loop exhausted without break)
    for sel in ORGANIC_SELECTORS:
        nodes = tree.css(sel)
        if nodes:
            results = [_extract_organic(n) for n in nodes]
            results = [r for r in results if r]
            if results:
                candidates.extend(results)
                break
    else:
        # D4: cascade exhausted alert — log warning (never logs the HTML)
        log.warning("parse_cascade_exhausted")
        candidates.extend(_extract_by_h3(tree))

    # Carousel (independent loop)
    for sel in CAROUSEL_SELECTORS:
        nodes = tree.css(sel)
        if nodes:
            carousel_results = [_extract_carousel(n) for n in nodes if _extract_carousel(n)]
            candidates.extend(carousel_results)
            break

    return candidates


# ──────────────────────────────────────────
# URL canonicalization + dedupe (SEARCH-05)
# ──────────────────────────────────────────

STRIP_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "fbclid",
        "gclid",
        "ved",
        "usg",
        "sa",
        "ei",
    }
)


def canonicalize_url(url: str) -> str:
    """
    Strip tracking params, lowercase netloc, remove trailing slash on path.
    STRIP_PARAMS frozenset from 02-RESEARCH.md §Code Examples (lines 1521-1536).
    """
    p = urlparse(url)
    qs = {k: v for k, v in parse_qs(p.query).items() if k not in STRIP_PARAMS}
    return urlunparse(
        (
            p.scheme,
            p.netloc.lower().rstrip("/"),
            p.path.rstrip("/") or "/",
            p.params,
            urlencode(qs, doseq=True),
            "",  # strip fragment
        )
    )


def dedupe(candidates: list[dict]) -> list[dict]:
    """
    Remove candidates with identical canonical URL (SEARCH-05).
    Mutates candidate['url'] to canonical form in-place.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for c in candidates:
        key = canonicalize_url(c["url"])
        if key not in seen:
            seen.add(key)
            c["url"] = key
            out.append(c)
    return out


# ──────────────────────────────────────────
# Junk-domain blocklist (SEARCH-06 / D9)
# ──────────────────────────────────────────

JUNK_DOMAINS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "reddit.com",
        "www.reddit.com",
        "wikipedia.org",
        "es.wikipedia.org",
        "www.wikipedia.org",
        "medium.com",
        "www.medium.com",
    }
)
JUNK_DOMAIN_SUFFIXES = (".fandom.com", ".gov.ar", ".medium.com")


def is_junk(url: str) -> bool:
    """
    Return True if URL's host is in the junk-domain blocklist (D9).
    Evaluated against host (netloc) BEFORE LLM step.
    §Code Examples lines 1551-1565.
    """
    host = urlparse(url).netloc.lower()
    if host in JUNK_DOMAINS:
        return True
    return any(host.endswith(s) for s in JUNK_DOMAIN_SUFFIXES)


# ──────────────────────────────────────────
# Re-rank (SEARCH-07)
# ──────────────────────────────────────────


def rerank(candidates: list[dict], max_results: int = 15) -> list[dict]:
    """
    Re-rank by (has_price DESC, fresh DESC, llm_confidence DESC).
    §Code Examples lines 1568-1576.
    """

    def sort_key(c: dict):
        has_price = 1 if c.get("price") else 0
        fresh = 1 if c.get("fresh") is True else 0
        confidence = c.get("llm_confidence", 0.0)
        return (has_price, fresh, confidence)

    return sorted(candidates, key=sort_key, reverse=True)[:max_results]
