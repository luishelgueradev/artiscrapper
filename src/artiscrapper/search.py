"""
SERP URL builder + four-level parser cascade + URL canonicalization + dedupe + blocklist + rerank.
Pattern 9 (build_serp_url), §Code Examples (cascade + canonicalize + dedupe + is_junk + rerank)
from 02-RESEARCH.md.
SEARCH-03: pws=0&safe=off (D3). SEARCH-04: parser cascade with alert (D4). SEARCH-05: canonicalize + dedupe.
SEARCH-06: junk-domain blocklist (D9). SEARCH-07: re-rank.
OBS-05: NEVER log title, snippet, url, or reason.
"""

import re
from urllib.parse import parse_qs, quote, quote_plus, urlencode, urlparse, urlunparse

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
# PARITY-02: Shopping panel ads (Google PLA = Product Listing Ads). Aditivo al
# organic + carousel — los pla-units sponsoreados traen URL canonical real
# (no sintética) y precio cierto, y son el bloque de mayor pérdida en el parser
# original (medición Exp 1-3, ver reporte). Selector contenedor `div.pla-unit`
# es semántico — los selectores INTERNOS (VbBaOe, UsGWMe, OkcyVb) son
# obfuscados y pueden rotar trimestralmente; cuando lo hagan, _extract_pla_unit
# retorna None silenciosamente y el parser sigue sirviendo organic+carousel.
PLA_SELECTORS = [
    "div.pla-unit",
]

# ──────────────────────────────────────────
# Regex-based commercial-data extraction
# ──────────────────────────────────────────
# Google rotates obfuscated CSS classes (LI0TWe, lmQWe, zxVpA, etc.) ~trimestrally,
# so we extract from the node's text content via regex — robust to class churn.

# AR price formats: $5.000,00 / $ 5.000,00 / $18.032,30 / ARS 5000 / U$S 5000.
# NBSP (\xa0) shows up between '$' and digits in Google's HTML — strip during normalize.
#
# Bug fix (0.2.1 / PARITY-03): the prior pattern `[\d](?:[\d.,]*\d)?` is greedy
# and absorbs trailing digits when a store name with digits is concatenated
# without a separator. Real-world failure case in carousel text:
#   "threezero Figura ... Robo-Dou$ 410.420,311001hobbies.es" → matched
#   "$ 410.420,311001" instead of the correct "$ 410.420,31".
# The v2 pattern requires `,DD` closure (mandatory 2 decimals for AR prices
# with thousands) or an integer with negative-lookahead (for legacy ARS 5000
# / U$S 5000 formats without decimals). Validated against 10 cases in the
# reporte (.planning/PARSER-VISUAL-PARITY-2026-06-05.md §7 Patch 2).
_PRICE_RE = re.compile(
    r"(?:\$|ARS|U\$S)\s?(?:&nbsp;)?\s?"
    r"(?:"
    r"[1-9]\d{0,2}(?:\.\d{3})*,\d{2}"  # $1.397.000,00 / $5.000,00 (closes at ,DD)
    r"|"
    r"[1-9]\d{2,7}(?![\d.,])"  # ARS 5000 / U$S 5000 (integer, no decimals)
    r")",
    re.IGNORECASE,
)
# Installment pattern: "$4.056,97/mes x 6" or "x 6 cuotas de $4.056,97 sin interés".
# The `x N` suffix is captured optionally, with whitespace mandatory after the digit
# so we don't bleed into "x 6Mercadolibre" (no separator) trailing text.
_INSTALLMENT_RE = re.compile(
    r"\$\s?[\d.,]+\s?/\s?mes(?:\s+x\s?\d+\b)?"
    r"|x\s?\d+\s+cuotas?(?:\s+de\s+\$\s?[\d.,]+)?(?:\s+sin\s+inter[eé]s)?",
    re.IGNORECASE,
)
# Stock signals (positive/negative)
_STOCK_AGOTADO_RE = re.compile(r"\b(?:agotado|sin\s+stock)\b", re.IGNORECASE)
_STOCK_OK_RE = re.compile(r"\b(?:stock\s+disponible|en\s+stock|disponible)\b", re.IGNORECASE)
_SHIPPING_FREE_RE = re.compile(r"env[íi]o\s+gratis|llega\s+gratis|free\s+shipping", re.IGNORECASE)
# Rating: "4.5 ★" / "4,5 estrellas" / "(1.234)" reviews count
_RATING_RE = re.compile(r"\b\d[.,]\d(?:\s?★|\s+estrellas?|\s+stars?)?", re.IGNORECASE)
# Store hint: the domain-ish token Google appends at the end of a card (typically
# "Mercadolibre.com.ar", "Falabella.com", "Lspalermo.com.ar"). Allow but don't require
# trailing whitespace — sometimes more text follows. Reject pure-emoji or noisy matches
# by requiring the domain to start with a letter and contain ".com".
# Note: NO leading \b — carousel text often concatenates digits and store ("x 6Mercadolibre…"),
# and \b between two word chars never matches. The leading letter character class is enough
# to anchor the start of a real store name.
_STORE_HINT_RE = re.compile(
    r"([A-Za-zÁÉÍÓÚÑñ][A-Za-z0-9ÁÉÍÓÚáéíóúÑñ\-]{2,30}\.com(?:\.[a-z]{2,3})?)(?:\b|$)"
)


def _normalize_price_text(s: str) -> str:
    """Strip NBSP and excess whitespace so '$\xa05.000,00' becomes '$5.000,00'."""
    return s.replace("\xa0", "").replace(" ", "").strip()


def _extract_commercial_signals(text: str) -> dict:
    """
    Pull price, installment, stock, shipping, rating, store from the node's text content.
    Returns a dict with only the keys that matched (sparse — caller merges into candidate).
    """
    if not text:
        return {}
    out: dict = {}
    # Price: take the FIRST monetary token (cards typically show the actual price first,
    # then installment plan). Skip pure-decimal floats < 100 (usually rating numbers).
    for m in _PRICE_RE.finditer(text):
        raw = m.group(0)
        norm = _normalize_price_text(raw)
        # Filter rating numbers like "$3.5" that aren't real prices
        digits = re.sub(r"[^\d]", "", norm)
        if len(digits) >= 3:  # at least 3 digits — real prices in AR are $100+
            out["price_in_card"] = norm
            break
    # Installments
    inst = _INSTALLMENT_RE.search(text)
    if inst:
        out["installments"] = _normalize_price_text(inst.group(0))
    # Stock: prefer the more specific signal
    if _STOCK_AGOTADO_RE.search(text):
        out["stock"] = "out_of_stock"
    elif _STOCK_OK_RE.search(text):
        out["stock"] = "in_stock"
    # Shipping
    if _SHIPPING_FREE_RE.search(text):
        out["free_shipping"] = True
    # Rating (only capture a clean N.N pattern, not random decimals)
    rm = _RATING_RE.search(text)
    if rm:
        rating_str = rm.group(0).strip()
        # Only keep if it's followed by a star/word marker — pure decimals are noisy
        if "★" in rating_str or "estrella" in rating_str.lower() or "star" in rating_str.lower():
            out["rating"] = rating_str
    # Store: take the LAST domain-shaped token in the text (cards end with the store).
    matches = list(_STORE_HINT_RE.finditer(text.replace("\xa0", " ")))
    if matches:
        out["store_hint"] = matches[-1].group(1).strip()
    return out


def _extract_organic(node) -> dict | None:
    """
    Extract a candidate dict from an organic SERP result node.
    Pulls URL/title/snippet via known selectors, then mines commercial signals
    (price, installments, stock, shipping, rating, store) from the node's full text via regex.
    """
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

    # Commercial signals via regex on the entire node text. Robust to Google's
    # obfuscated class rotation; covers Shopping-augmented organic results that
    # carry price/stock/installment without matching the (often-renamed) selectors.
    signals = _extract_commercial_signals(node.text(strip=True))

    candidate: dict = {
        "url": href,
        "title": title,
        "snippet": snippet,
        "price_in_card": signals.get("price_in_card"),
        "has_price": bool(signals.get("price_in_card")),
        "flags": [],
    }
    # Merge optional enrichment without clobbering core fields
    for key in ("installments", "stock", "free_shipping", "rating", "store_hint"):
        if key in signals:
            candidate[key] = signals[key]
    return candidate


def _synthesize_carousel_url(title: str | None, store_hint: str | None) -> str:
    """
    Carousel items don't expose a direct <a href> — Google constructs the click-through
    URL via JS using data-iid/data-pid encoded in inline <script>. Without executing JS
    we can't recover the exact PDP URL, so we generate a Google-search URL that the
    consumer can open to land on the actual listing.
    """
    parts = [title or "producto"]
    if store_hint:
        parts.append(f"site:{store_hint.lower()}")
    return "https://www.google.com/search?q=" + quote_plus(" ".join(parts))


def _extract_carousel(node) -> dict | None:
    """
    Extract a candidate dict from a carousel item node.
    Carousel items have no direct <a href> (Google uses JS click handlers — see
    _synthesize_carousel_url docstring). We extract title + commercial signals from
    the text and synthesize a search-style URL.
    """
    text = node.text(strip=True)
    if not text:
        return None

    signals = _extract_commercial_signals(text)
    if "price_in_card" not in signals:
        # No price in the card → not a useful product card; skip
        return None

    # Title: substring before the first monetary token (carousels lay out
    # "Title $price installments Store"). Fall back to the whole text if no
    # price match position is recoverable.
    title_text = text
    price_match = _PRICE_RE.search(text)
    if price_match:
        title_text = text[: price_match.start()]
    # Normalize NBSP + collapse whitespace, then strip card-edge punctuation
    title_text = re.sub(r"\s+", " ", title_text.replace("\xa0", " ")).strip(" ·-—|")
    # Strip trailing store hint if it bled into the title
    store = signals.get("store_hint")
    if store and title_text.lower().endswith(store.lower()):
        title_text = title_text[: -len(store)].rstrip(" ·-—|")
    # Hard cap on title length (some carousels have long product descriptions)
    title_text = title_text[:250] or None

    href = _synthesize_carousel_url(title_text, store)

    candidate: dict = {
        "url": href,
        "title": title_text,
        "snippet": None,
        "price_in_card": signals["price_in_card"],
        "has_price": True,
        "flags": ["carousel", "synthetic_url"],
    }
    for key in ("installments", "stock", "free_shipping", "rating", "store_hint"):
        if key in signals:
            candidate[key] = signals[key]
    return candidate


def _extract_pla_unit(node) -> dict | None:
    """
    Extract a candidate dict from a Google Shopping pla-unit cell (PARITY-02).

    pla-unit = sponsored ad slot. Características distintivas vs carousel:
    - URL canonical real (`mercadolibre.com.ar/.../p/MLA*`, `nike.com.ar/...`),
      NO sintetizada como en `_synthesize_carousel_url`.
    - Precio principal en `<span class="VbBaOe">$X.XXX,XX</span>`.
    - Store hint en `<div class="UsGWMe">` (aria-label `De {store}`).
    - Cuota mensual opcional en `<div class="OkcyVb">` (`$X durante 6...`).
    - El título vive en `[role=heading]`, NO en aria-label del `<a>` que
      Google deja vacío (` por  de Mercadolibre.com.ar`).

    Hay dos `<a>` por cell:
    - `/aclk?...` — display:none tracking pixel; ignorar.
    - URL real al producto con merchant params (matt_tool=, utm_source=, etc.).

    Returns None si no encontramos título o URL real (selector rotation, HTML
    parcial). El parser sigue funcionando con organic + carousel; el bloque
    pla-unit es opcional, no blocking.
    """
    title_el = node.css_first("[role=heading]")
    title = title_el.text(strip=True) if title_el else None

    href = None
    for a in node.css("a[href]"):
        h = a.attributes.get("href", "")
        if h.startswith("http") and "/aclk?" not in h:
            # selectolax devuelve URLs con `&amp;` HTML-encoded; cortamos al
            # primer & para tener el path + primer query param (suficiente
            # para identificar el producto). Si se necesita la query completa,
            # usar `html.unescape(h)`.
            href = h.split("&amp;")[0]
            break
    if not href or not title or "google.com" in href:
        return None

    price_el = node.css_first("span.VbBaOe")
    price = price_el.text(strip=True).replace("\xa0", "") if price_el else None

    store_el = node.css_first("div.UsGWMe")
    store = store_el.text(strip=True) if store_el else None

    inst_el = node.css_first("div.OkcyVb")
    inst = inst_el.text(strip=True).replace("\xa0", "") if inst_el else None

    return {
        "url": href,
        "title": title,
        "snippet": None,
        "price_in_card": price,
        "has_price": bool(price),
        "store_hint": store,
        "installments": inst,
        "flags": ["pla_unit", "sponsored"],
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

    # PARITY-02: pla-unit pass (Google Shopping ads — sponsored).
    # Additive al organic cascade y al carousel: NO los reemplaza, NO compite con
    # ellos. La pla-unit es el bloque sponsoreado de mayor valor (URL canonical
    # real, precio cierto). Dedupe interno por URL para evitar duplicar productos
    # cuando el panel y un g-scrolling-carousel paralelo listan el mismo producto.
    # El dedupe global (`dedupe()`) corre después y combina con organic+carousel.
    # Ver .planning/PARSER-VISUAL-PARITY-2026-06-05.md §7 Patch 3.
    pla_seen: set[str] = set()
    for sel in PLA_SELECTORS:
        for n in tree.css(sel):
            c = _extract_pla_unit(n)
            if c and c["url"] not in pla_seen:
                pla_seen.add(c["url"])
                candidates.append(c)

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
# Heuristic pre-classifier (Path B perf fix, 2026-06-04)
# ──────────────────────────────────────────
#
# Pre-classify candidates before the LLM curator. Splits into 3 buckets:
#   - kept_high_conf  → bypass LLM, go directly to visit pass
#   - ambiguous       → still need LLM decision
#   - dropped         → never going to be a product, skip entirely
#
# Empirical basis (.planning/PERFORMANCE-AUDIT-2026-06-04.md §1, §4):
# Against the 50 labeled Phase 1 fixtures (42 products / 8 non-products),
# the LLM alone scores precision 92.5%, recall 88.1%. The heuristic alone
# scores precision 100%, recall 78.6%. The hybrid (this function +
# curate_candidates only on ambiguous) scores precision 92.7%, recall
# 90.5%, F1 0.92 in 7.6s instead of 35s. The heuristic resolves 76% of
# typical candidates; only the 24% ambiguous get LLM-classified, cutting
# router load by 4x and cold path latency by ~30s.

# Known commercial stores (AR-first). Suffix match against URL host —
# `host.endswith(store)` catches subdomains (e.g., `listado.mercadolibre.com.ar`).
KNOWN_STORES: frozenset[str] = frozenset(
    {
        # Mercado Libre regional
        "mercadolibre.com.ar",
        "mercadolibre.com",
        "mercadolibre.com.mx",
        "mercadolibre.cl",
        "mercadolibre.com.uy",
        # Amazon regional
        "amazon.com.ar",
        "amazon.com",
        # AR retail majors
        "garbarino.com",
        "fravega.com",
        "tiendamia.com",
        "musimundo.com",
        "carrefour.com.ar",
        "cetrogar.com.ar",
        "compraonline.com.ar",
        "casaalbano.com.ar",
        "naldo.com.ar",
        # AR auto-parts specialists (relevant to Sánchez Repuestos)
        "frogautopartes.com.ar",
    }
)

# Title patterns that signal informational content (blog/guide/comparison),
# never a product page. Lowercased before matching.
BLOG_TITLE_PATTERNS: tuple[str, ...] = (
    "como saber",
    "cómo saber",
    "qué elegir",
    "que elegir",
    "qué es",
    "que es",
    "diferencia entre",
    "tabla de equivalencias",
    "comparativa",
    "cada cuánto",
    "cada cuanto",
    "guía",
    "tutorial",
    "review",
    "opinión",
    "opinion",
    "vs.",
)

# File extensions that are never product pages.
DOCUMENT_EXTENSIONS: tuple[str, ...] = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
)

# URL substrings that signal forums/Q&A, never product pages.
FORUM_PATTERNS: tuple[str, ...] = (
    "reddit.com",
    "/forum/",
    "/foro/",
    "quora.com",
    "stackexchange.com",
    "/forums/",
)


def heuristic_pre_classify(
    candidates: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    Split candidates into (kept_high_confidence, ambiguous).

    Returns:
        - ``kept_high_confidence``: candidates with price_in_card OR known store host.
          Each tagged with ``_pre_class_reason`` for downstream logging/metrics.
          Bypass the LLM curator entirely.
        - ``ambiguous``: candidates without clear product signals. These still
          need ``curate_candidates`` to decide.

    Candidates matching any drop heuristic — junk-domain, forum, document
    extension, blog-style title — are **dropped entirely** (not returned in
    either bucket). The LLM would have descarted them with the same confidence.

    Time complexity: O(n × constants). For typical 50-60 candidates: <5ms.

    Empirical accuracy (vs 50 labeled Phase 1 candidates):
        - Precision (hybrid w/ LLM): 92.7%
        - Recall (hybrid w/ LLM):    90.5%
        - F1 (hybrid w/ LLM):        0.92
        - % resolved heuristically:  76% (only 24% sent to LLM)

    See `.planning/PERFORMANCE-AUDIT-2026-06-04.md` for the benchmark.
    """
    kept: list[dict] = []
    ambiguous: list[dict] = []

    for cand in candidates:
        url = cand.get("url") or ""
        title = (cand.get("title") or "").lower()
        url_lower = url.lower()

        # Hard-drop signals — neither LLM nor visit could rescue these.
        if is_junk(url):
            continue
        if any(p in url_lower for p in FORUM_PATTERNS):
            continue
        if url_lower.endswith(DOCUMENT_EXTENSIONS):
            continue
        if any(p in title for p in BLOG_TITLE_PATTERNS):
            continue

        # High-confidence keep signal #1: SERP cards already gave us a price.
        if cand.get("price_in_card"):
            kept.append({**cand, "_pre_class_reason": "price_in_card"})
            continue

        # High-confidence keep signal #2: host is a known commercial store.
        # tldextract is not used here — simple suffix match is enough and
        # avoids a second TLD-parsing pass per candidate (visit.py already
        # does the rigorous one via tldextract for the MELI guard).
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if any(host.endswith(store) for store in KNOWN_STORES):
            kept.append({**cand, "_pre_class_reason": "known_store"})
            continue

        # Ambiguous — needs LLM judgment.
        ambiguous.append(cand)

    return kept, ambiguous


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
