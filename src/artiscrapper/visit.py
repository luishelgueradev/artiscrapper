"""
Visit pass module: visit_candidates + classify_response + extract_product (D12 HAND-ROLL).
Pattern 4 from 02-RESEARCH.md (lines 650-768) — visit orchestrator + DEFAULT_HEADERS.
Pattern 6 from 02-RESEARCH.md (lines 943-1063) — hand-rolled extractor cascade.
VISIT-01: skip-if-you-can. VISIT-02: http2 + semaphores. VISIT-03: per-request timeout.
VISIT-04: DEFAULT_HEADERS (D11). VISIT-05: classify_response. VISIT-06: extractor cascade.
VISIT-07: no retry on failure. VISIT-08: MELI guard (FIRST check in visit_one).
D12: HAND-ROLL confirmed 9/10 jsonld-sufficient. Do NOT import extruct.
"""

import asyncio
import json
import re
from collections import defaultdict
from urllib.parse import urlparse

import httpx
import structlog
from selectolax.parser import HTMLParser

from .metrics import metrics

log = structlog.get_logger()

GLOBAL_VISIT_CAP = 8
PER_HOST_CAP = 2

# D11: Chromium-146 headers — Sec-Fetch-Site: cross-site + Referer: https://www.google.com/
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="146", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",  # D11: came-from-google signal
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.google.com/",  # D11 invariant
}

# VISIT-05: dead page markers
DEAD_MARKERS = (
    "404",
    "no encontrad",
    "not found",
    "no disponible",
    "producto agotado",
    "sold out",
    "producto no existe",
)
SOFT_404_PATHS = {"", "/", "/home", "/index.html", "/buscar", "/search", "/s"}

# AR price formats: $18.032,30 / ARS 18.032,30 / $ 18.032 / pesos 5000
# Three alternate groups: ARS/ar$ prefix, pesos prefix, dollar-sign only
# Based on Pattern 6 from 02-RESEARCH.md — extended to handle ARS-without-dollar format
AR_PRICE_PATTERN = re.compile(
    r"(?:"
    r"(?:ARS|ar\$)\s*[^a-zA-Z\n]{0,3}?(\d[\d.,]*\d|\d+)"  # ARS NNN or ar$ NNN
    r"|"
    r"pesos\s+(\d[\d.,]*\d|\d+)"  # pesos NNN
    r"|"
    r"[$]\s*(\d[\d.,]*\d|\d+)"  # $NNN or $ NNN
    r")",
    re.IGNORECASE,
)


def classify_response(response: httpx.Response) -> str:
    """
    VISIT-05: live-vs-dead classification.
    Pattern 4 from 02-RESEARCH.md lines 741-767.
    Returns "live", "dead", or "failed".
    """
    if response.status_code >= 400:
        return "failed"
    try:
        final_path = urlparse(str(response.url)).path.rstrip("/") or "/"
    except RuntimeError:
        # response.url requires a request to be set (httpx design)
        # When no URL is available, treat as unknown path
        final_path = ""
    if final_path in SOFT_404_PATHS or final_path.startswith("/buscar"):
        return "dead"  # redirect-to-home soft-404
    ct = response.headers.get("content-type", "")
    if "html" not in ct:
        return "failed"
    if len(response.content) < 5_000:
        return "failed"  # body size floor
    tree = HTMLParser(response.text)
    title = (tree.css_first("title").text() if tree.css_first("title") else "").lower()
    h1 = (tree.css_first("h1").text() if tree.css_first("h1") else "").lower()
    if any(m in title or m in h1 for m in DEAD_MARKERS):
        return "dead"
    return "live"


# ──────────────────────────────────────────
# Pattern 6: Hand-rolled extractor cascade (D12 HAND-ROLL confirmed)
# VISIT-06 — verbatim from 02-RESEARCH.md lines 958-1063
# ──────────────────────────────────────────


def extract_jsonld_product(tree: HTMLParser) -> dict | None:
    """
    JSON-LD Product extraction.
    Handles @graph wrappers (Tiendanube/VTEX pattern) — required for casasusy, dphidraulica, lspalermo.
    Pattern 6 from 02-RESEARCH.md lines 958-979.
    """
    for script in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text())
        except (json.JSONDecodeError, ValueError):
            continue
        items = data if isinstance(data, list) else [data]
        # Flatten @graph (Tiendanube emits @graph wrapper with Product inside)
        expanded = []
        for item in items:
            if isinstance(item, dict) and "@graph" in item:
                expanded.extend(item["@graph"])
            else:
                expanded.append(item)
        for item in expanded:
            if not isinstance(item, dict):
                continue
            t = item.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                return item
    return None


def extract_og_product(tree: HTMLParser) -> dict | None:
    """
    OG product:* extraction (NOT og:price — canonical is product:price:amount).
    Pattern 6 from 02-RESEARCH.md lines 981-996.
    """
    metas: dict[str, str] = {}
    for m in tree.css("meta[property]"):
        prop = m.attributes.get("property", "")
        content = m.attributes.get("content", "")
        if prop and content:
            metas[prop] = content
    if "product:price:amount" not in metas:
        return None
    return {
        "price": metas["product:price:amount"],
        "currency": metas.get("product:price:currency", "ARS"),
        "name": metas.get("og:title"),
        "image": metas.get("og:image"),
    }


def extract_microdata_product(tree: HTMLParser) -> dict | None:
    """
    Microdata itemprop (legacy Magento/older Tiendanube templates).
    Pattern 6 from 02-RESEARCH.md lines 998-1012.
    """
    product_el = tree.css_first('[itemtype$="/Product"]')
    if not product_el:
        return None
    price_el = product_el.css_first('[itemprop="price"]')
    if price_el:
        price_val = price_el.attributes.get("content") or price_el.text(strip=True)
        currency_el = product_el.css_first('[itemprop="priceCurrency"]')
        currency = currency_el.attributes.get("content", "ARS") if currency_el else "ARS"
        return {"price": price_val, "currency": currency}
    return None


def _price_group(m: re.Match) -> str | None:
    """Extract the first non-None capture group from AR_PRICE_PATTERN match."""
    return m.group(1) or m.group(2) or m.group(3)


def extract_price_regex(tree: HTMLParser) -> dict | None:
    """
    AR price regex fallback — last resort.
    Scopes to price-like elements first, then full text.
    Pattern 6 from 02-RESEARCH.md lines 1013-1032.
    """
    # Scope to price-like elements first
    for selector in (".price", ".precio", ".product-price", '[itemprop="price"]'):
        el = tree.css_first(selector)
        if el:
            m = AR_PRICE_PATTERN.search(el.text(strip=True))
            if m:
                raw = _price_group(m) or ""
                return {"price": raw.replace(".", "").replace(",", "."), "currency": "ARS"}
    # Full-text fallback
    body_text = tree.body.text() if tree.body else ""
    m = AR_PRICE_PATTERN.search(body_text)
    if m:
        raw = _price_group(m) or ""
        return {"price": raw.replace(".", "").replace(",", "."), "currency": "ARS"}
    return None


def _extract_price_from_offers(offers: dict | list) -> str | None:
    """
    Helper to extract price from an offers object (Offer or AggregateOffer).
    Handles nested priceSpecification (WooCommerce/mayoristafrog pattern).
    Handles AggregateOffer with lowPrice.
    """
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if not isinstance(offers, dict):
        return None

    # Direct price field
    price = offers.get("price")
    if price is not None:
        return str(price)

    # WooCommerce: priceSpecification list
    ps = offers.get("priceSpecification", [])
    if isinstance(ps, list) and ps:
        p = ps[0].get("price")
        if p is not None:
            return str(p)

    # AggregateOffer: lowPrice
    low = offers.get("lowPrice")
    if low is not None:
        return str(low)

    # Nested offers inside AggregateOffer
    nested = offers.get("offers", [])
    if isinstance(nested, list) and nested:
        p = nested[0].get("price")
        if p is not None:
            return str(p)
    elif isinstance(nested, dict):
        p = nested.get("price")
        if p is not None:
            return str(p)

    return None


def extract_product(html: str) -> dict | None:
    """
    Full extraction cascade: JSON-LD → OG → microdata → AR-regex.
    Returns normalized dict with 'price', 'currency', 'name' (when available).
    Pattern 6 from 02-RESEARCH.md lines 1034-1063.
    """
    tree = HTMLParser(html)
    if result := extract_jsonld_product(tree):
        offers = result.get("offers", {})
        price = _extract_price_from_offers(offers)
        if price is None:
            price = str(result.get("price")) if result.get("price") is not None else None

        # Get currency from offers
        currency = "ARS"
        offers_obj = (
            offers
            if isinstance(offers, dict)
            else (offers[0] if isinstance(offers, list) and offers else {})
        )
        if isinstance(offers_obj, dict):
            currency = offers_obj.get("priceCurrency", "ARS")

        return {
            "price": price,
            "currency": currency,
            "name": result.get("name"),
            "availability": offers_obj.get("availability")
            if isinstance(offers_obj, dict)
            else None,
            "date_modified": result.get("dateModified"),
        }
    if result := extract_og_product(tree):
        return {
            "price": result.get("price"),
            "currency": result.get("currency", "ARS"),
            "name": result.get("name"),
            "availability": None,
            "date_modified": None,
        }
    if result := extract_microdata_product(tree):
        return {
            "price": result.get("price"),
            "currency": result.get("currency", "ARS"),
            "name": None,
            "availability": None,
            "date_modified": None,
        }
    if result := extract_price_regex(tree):
        return {
            "price": result.get("price"),
            "currency": "ARS",
            "name": None,
            "availability": None,
            "date_modified": None,
        }
    return None


# ──────────────────────────────────────────
# Visit orchestrator (VISIT-02: http2 + semaphores)
# Pattern 4 from 02-RESEARCH.md lines 683-737
# ──────────────────────────────────────────


async def visit_candidates(
    candidates: list[dict],
    visit_timeout_s: int = 10,
) -> list[dict]:
    """
    Visit only candidates that pass skip-if-you-can (VISIT-01).
    Returns enriched candidates with price/freshness filled in.
    Real-URL-only: operates on candidate["url"] from SERP parser — never constructs URLs.
    VISIT-03: visit_timeout_s is the per-request timeout (passed from SearchRequest).
    """
    global_sem = asyncio.Semaphore(GLOBAL_VISIT_CAP)
    host_sems: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(PER_HOST_CAP))

    async def visit_one(candidate: dict) -> dict:
        url = candidate["url"]

        # VISIT-08: FIRST CHECK — never visit *.mercadolibre.*
        # This is a security control (architecture-level), not optional.
        if "mercadolibre." in urlparse(url).netloc:
            candidate["flags"] = candidate.get("flags", []) + ["meli_skip"]
            return candidate

        # VISIT-01: SECOND CHECK — skip-if-you-can
        if (
            candidate.get("price") is not None
            or candidate.get("freshness_signal") == "live_marketplace"
        ):
            return candidate

        host = urlparse(url).netloc

        async with global_sem, host_sems[host]:
            try:
                async with httpx.AsyncClient(
                    http2=True,
                    headers=DEFAULT_HEADERS,
                    follow_redirects=True,
                    timeout=httpx.Timeout(
                        connect=3.0, read=float(visit_timeout_s), write=3.0, pool=2.0
                    ),
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                ) as client:
                    resp = await client.get(url)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError):
                candidate["visit_failed"] = True
                metrics.visit_failed_total[host] += 1  # OBS-06
                return candidate
            except Exception:
                candidate["visit_failed"] = True
                metrics.visit_failed_total[host] += 1  # OBS-06
                return candidate

            # VISIT-07: no retry on failure
            outcome = classify_response(resp)
            if outcome == "dead":
                candidate["skip_dead"] = True
                return candidate
            if outcome == "failed":
                candidate["visit_failed"] = True
                metrics.visit_failed_total[host] += 1  # OBS-06
                return candidate

            extracted = extract_product(resp.text)
            if extracted:
                candidate.update(extracted)
            return candidate

    results = await asyncio.gather(*[visit_one(c) for c in candidates])
    return list(results)
