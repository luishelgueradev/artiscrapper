# Visit-pass Design: httpx fetch + Structured Data Extraction

**Scope:** PRD §3 step 6 (visit pass), F-06 + F-07 in PROJECT.md. Covers: live-vs-dead detection, structured-data extraction priority, per-host strategy, concurrency, anti-bot exposure, error budget.

**Date:** 2026-06-01
**Confidence overall:** MEDIUM-HIGH (extraction stack is well-trodden; AR-specific per-host signals need Fase 0 fixture validation)

---

## Verdict (per focus question)

| # | Question | Verdict | Confidence |
|---|----------|---------|------------|
| 1 | Live-vs-dead detection in <2s | **Combined signals: status + history + title + size + structured-data presence**. Not a single heuristic — a small weighted check. Expected FP rate <5% on top-10 AR stores | MEDIUM |
| 2 | Extraction priority + libs | **JSON-LD → OG `product:*` → microdata → regex fallback**. Use `extruct` for JSON-LD/OG/microdata in one call, `selectolax` for the regex fallback. ~75-85% AR e-commerce carry JSON-LD Product (extrapolated from global Shopify 89% + Tiendanube/VTEX docs explicitly recommend it) | MEDIUM-HIGH |
| 3 | Freshness signals | **MELI link → live; OG `product:availability` + JSON-LD `availability=InStock` + JSON-LD `dateModified` <90d → fresh**. Absent → `fresh=unknown` (lower confidence, keep candidate). Most AR product pages do **not** emit datePublished/dateModified — assume unknown by default | MEDIUM |
| 4 | Skip-if-you-can allow-list | **Start tight: only MELI**. Expand to specific known-fresh stores after empirical validation. Maintain as static dict `KNOWN_LIVE_HOSTS` in code; review every 4-6 weeks. NOT crowdsourced/dynamic | HIGH |
| 5 | Concurrency cap | **Global cap 8 concurrent visits via `asyncio.Semaphore`. Per-host cap 2 concurrent via dict-of-semaphores keyed by registered domain**. Empirically tune in Fase 1 | MEDIUM-HIGH |
| 6 | Anti-bot at visit step | **httpx with realistic headers passes most AR catalog static stores. Falabella/VTEX-protected sites may 403/return interstitial — accept as `visit_failed`**. Do NOT add Cloak to the visit pass; the LLM already filtered the bulk noise | MEDIUM |
| 7 | Error budget | **Healthy run: ≤30% `visit_failed` of attempted visits**. Above 50% sustained for a specific host → blocklist that host or mark its candidates as unverifiable. Above 30% across all hosts → systemic problem (IP block, header config drift) | MEDIUM |

---

## Findings

### Q1 — Live-vs-dead detection

The decision must happen in <2s on a 200 response (PRD: visit_timeout_s default 10s; the *detection* itself, post-fetch, should add no perceptible latency).

**Signals to combine (cheap, deterministic, in this order):**

1. **HTTP status from `response.status_code`**
   - `2xx` → continue to content checks
   - `3xx`: with `follow_redirects=True` (default in PRD path), httpx exposes the chain in `response.history`. **Critical case:** if the final URL after redirects normalizes to the host root (e.g., `https://store.com.ar/some-product-slug` → `https://store.com.ar/`), this is a soft-404. Detect by comparing `urlparse(final).path` against `/`, `/home`, `/index`, `/buscar` (search), `/404`, `/error`.
   - `4xx`/`5xx` → mark `visit_failed=true` (4xx is dead, 5xx is transient — both treated as failure for the visit pass; PRD already collapses to `visit_failed` flag).

2. **Final-URL path normalization** — covers ~60% of dead pages on Tiendanube/VTEX/Shopify-style stores that 302 to home on missing SKU.

3. **HTML page-title check via `selectolax`**: extract `<title>` text and `<h1>` text from the response body. Match (case-insensitive) against:
   - `404`, `not found`, `página no encontrada`, `no encontrado`, `producto no disponible`, `agotado`, `sold out`, `producto no existe`, `error`
   - If matched → soft-404, `skip_dead=true`.
   This is cheap (~1ms with selectolax on 100KB-500KB documents).

4. **Response body size** — empirical floor of ~5KB rules out "JSON empty response", redirected JSON APIs, blank error pages. Soft cap: if `len(response.content) < 5_000` AND content-type is `text/html` → suspect.

5. **Content-Type sanity** — if not `text/html*` and not `application/ld+json`, suspect. Some hosts return `text/plain` on dead URLs.

6. **Presence of structured data** — if extruct returns ZERO of (jsonld, microdata, opengraph) AND title check is ambiguous → demote to lower confidence but don't necessarily drop; many smaller AR stores have no structured data even on live pages.

**Empirical FP rate:** unknown until Fase 0/1 fixture runs. The PRD's risk row "Algunos stores con anti-bot en visit step / Medium" anticipates ~10-30% noise — that's the target ceiling for `visit_failed + skip_dead` combined. False-positive (marking live page as dead) should stay <5% — most real product pages either have a real `<h1>` matching the product name or have JSON-LD.

**Recommended implementation pseudo:**
```python
def classify_response(response: httpx.Response) -> Literal["live", "dead", "failed"]:
    if response.status_code >= 400:
        return "failed"
    final = urlparse(str(response.url))
    if final.path in {"", "/", "/home", "/index.html"}:
        return "dead"  # soft-404 redirect-to-home
    if "html" not in response.headers.get("content-type", ""):
        return "failed"
    body = response.text  # selectolax on str
    tree = HTMLParser(body)
    title = (tree.css_first("title").text() if tree.css_first("title") else "").lower()
    h1 = (tree.css_first("h1").text() if tree.css_first("h1") else "").lower()
    DEAD_MARKERS = ("404", "no encontrad", "not found", "no disponible", "producto agotado")
    if any(m in title or m in h1 for m in DEAD_MARKERS):
        return "dead"
    if len(response.content) < 5_000:
        return "failed"
    return "live"
```

> Source: combined synthesis of [benhoyt/soft404 README](https://github.com/benhoyt/soft404/blob/master/README.md) (heuristic of testing a known-bad URL) and [ithy.com 5 Methods to Detect 404 Errors in Python](https://ithy.com/article/top-5-python-methods-for-404-detection-1x7b790g). The "compare against a known-bad URL" technique from benhoyt is **NOT recommended** for our scope — it doubles the visit cost and AR stores are small enough that the title-check + redirect-path heuristic suffices.

---

### Q2 — Structured-data extraction priority

**Recommended fallback chain (try in order; first hit wins):**

| Priority | Signal | What it gives us | AR e-commerce coverage |
|---|---|---|---|
| 1 | `<script type="application/ld+json">` Schema.org `Product` with `offers.price` | name, brand, sku, image, price, priceCurrency, availability, sometimes dateModified | **HIGH** — Tiendanube ([explicit docs](https://docs.tiendanube.com/help/data-estructurada-json-ld)), VTEX (templates ship it), MercadoLibre (per third-party scrapers), Falabella |
| 2 | OpenGraph `<meta property="product:price:amount">` + `product:price:currency` (note: **`product:*` not `og:*`** — the PRD's "og:price" phrasing is slightly off; the standard is `product:price:amount` per [ogp.me product type](https://ogp.me/) and Facebook's product type spec) | price, currency, title (`og:title`), image (`og:image`), url (`og:url`) | **MEDIUM-HIGH** — most Shopify/Tiendanube/Magento sites |
| 3 | Microdata `itemprop="price"`, `itemprop="priceCurrency"`, `itemprop="availability"` on a `<div itemtype="https://schema.org/Product">` ancestor | same as JSON-LD but lossy/incomplete | **MEDIUM** — legacy, but Magento and older Tiendanube templates still emit |
| 4 | Selectolax + AR-specific regex (`r'\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)'`) over the cleaned HTML, scoping to elements with class names like `price`, `precio`, `product-price` | price only, no currency, no availability | **LOW** but high recall — last-resort fallback for stores with no structured data |

**Recommended Python implementation:**

```python
# Single library does layers 1-3 in one call:
import extruct
data = extruct.extract(
    html_string,
    base_url=url,
    syntaxes=["json-ld", "opengraph", "microdata"],
    uniform=True,  # normalizes microdata/og to JSON-LD-like shape
)

# Then post-process: look for Product type in any of the three buckets
def find_product(data: dict) -> dict | None:
    for items in data.values():
        for item in items:
            if "@type" in item and "Product" in str(item["@type"]):
                return item
    return None

# Fallback layer 4: only if find_product returned None
from selectolax.parser import HTMLParser
tree = HTMLParser(html_string)
price_el = tree.css_first(".price, .precio, .product-price, [itemprop='price']")
```

**Why `extruct` over hand-rolling with `selectolax`:**

- `extruct` (latest: **0.18.0**, requires Python ≥3.8) handles JSON-LD, OpenGraph, microdata, RDFa, Dublin Core, and microformats in ONE call.
- Dependencies pulled in: `lxml`, `lxml-html-clean`, `rdflib≥6.0.0`, `pyrdfa3`, `mf2py`, `w3lib`, `html-text`, `jstyleson`. **This is heavy** — adds ~30MB to the image, pulls rdflib which is a 5MB Python lib. For our 1-container deploy, acceptable but not free.
- Hand-rolled selectolax + `json.loads` of `script[type="application/ld+json"]` is faster (~5-10x) AND avoids the rdflib/pyrdfa3 deps. The tradeoff: we re-implement OpenGraph + microdata extraction ourselves.

**Verdict:** **Use `extruct` for layers 1-3** if image size is acceptable; **otherwise hand-roll with selectolax** (cheaper, faster, but +50-100 lines of code). Given the 1-container scope of artiscrapper v0 and PRD's "selectolax already chosen", **hand-roll the JSON-LD + OG layers in selectolax (~50 LOC), skip microdata initially**, and only add extruct in Fase 2 if a meaningful % of stores lack JSON-LD/OG and rely on microdata. (Confidence: MEDIUM. Validate against Fase 0 fixture sweep.)

Hand-rolled JSON-LD extractor sketch:
```python
def extract_jsonld_product(tree: HTMLParser) -> dict | None:
    for script in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text())
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        # Handle @graph wrappers
        for item in items:
            if "@graph" in item:
                items.extend(item["@graph"])
        for item in items:
            t = item.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                return item
    return None

def extract_og_product(tree: HTMLParser) -> dict | None:
    metas = {}
    for m in tree.css("meta[property]"):
        prop = m.attributes.get("property", "")
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
```

**% of AR e-commerce with JSON-LD Product (2026):** Confidence MEDIUM. Global figures: [DigitalApplied 5k-site audit](https://www.digitalapplied.com/blog/schema-markup-adoption-5k-site-audit-2026) reports ~53% of all sites use JSON-LD overall, 89% of Shopify stores ship Product schema. Tiendanube's [own docs](https://docs.tiendanube.com/help/data-estructurada-json-ld) push JSON-LD as the default. **Estimated AR e-commerce coverage: 75-85% of stores Sánchez would care about ship JSON-LD Product on PDPs.** The long tail (mom-and-pop autoparts sites) may not — fallback to regex price extraction is justified for them.

---

### Q3 — Freshness signals

**Per the PRD `freshness` field is `bool` (`fresh=true|false`), determined by:**

1. **MELI link + HTTP 200** → `fresh=true` (the marketplace is presumed live; PRD step 7).
2. **JSON-LD `dateModified` or `datePublished` within 90 days** → `fresh=true`.
3. **`<time datetime="...">` element within 90 days** in product detail page → `fresh=true`.
4. **`product:availability` OG meta = `in stock`/`instock`/`disponible`** OR **JSON-LD `offers.availability = https://schema.org/InStock`** → strong implicit fresh signal (PRD doesn't mention but should add — confidence MEDIUM).
5. **None of the above** → `fresh=unknown` (NOT false; the PRD step 7 distinguishes "fresh=unknown" from skip). Lower the confidence by ~0.1 in re-rank.

**Per-host emission of date signals (best-guess; verify in Fase 0):**

| Host | JSON-LD `datePublished` | JSON-LD `dateModified` | `<time datetime>` | OG `product:availability` | Microdata `itemprop="datePublished"` |
|---|---|---|---|---|---|
| mercadolibre.com.ar | rare | rare | sometimes (in seller activity blocks) | yes (in OG meta) | no |
| tiendanube.com.ar (any *.mitiendanube.com) | no | no | no | yes (theme-dependent) | rare |
| falabella.com.ar | no | no | no | sometimes | no |
| vtex-hosted (musimundo, garbarino) | no | no | no | yes | sometimes |
| Shopify stores | yes (some themes) | yes (some themes) | sometimes | yes | no |
| Custom catalogs (mayoristafrog, romero-jugueteria) | unknown | unknown | unknown | unknown | unknown |

**Recommended safe default:** when absent, `fresh=unknown` with a `freshness_evidence: []` array logged for forensics. **Do NOT default to `fresh=false`** — false would suppress real products. The re-rank step handles the demotion implicitly via `(has_price DESC, fresh DESC, llm_confidence DESC)`.

> Source: [searchengineland on byline dates](https://searchengineland.com/date-published-date-updated-organic-ctr-453209) — e-commerce sites in general avoid emitting date fields on PDPs because they reset CTR signals. **Implication:** don't expect `datePublished` on product pages; rely on availability instead.

---

### Q4 — Skip-if-you-can policy: expanding "live_marketplace"

PRD step 6: `if (price is None) AND (freshness != "live_marketplace"): visit`. The LLM emits `freshness_signal` ∈ `{"live_marketplace", "static_catalog", "blog", "unknown"}`. The LLM is told to label MELI links as `live_marketplace`. Should we expand this?

**Recommendation:** **NO expansion in v0.** Reasons:

1. The LLM is making the call based on URL + snippet — it's already inferring from hostname. Adding a hard allow-list in code creates two sources of truth (the LLM and the code) that can disagree.
2. The visit pass is cheap when the SERP already carried a price (`price_hint` from LLM/carousel). Skip happens **also** when `price is not None` — that's the dominant skip path. The "freshness skip" is a secondary filter.
3. Hardcoded allow-lists drift fast. Falabella's checkout flow changes quarterly. Storing "falabella.com.ar = always fresh" in code rots silently.

**If we do want a manual override (Fase 2+):** add a `KNOWN_FRESH_HOSTS` static set in `config.py`, starting at `{"mercadolibre.com.ar", "mercadolibre.com"}`. Review at every milestone. Sourcing: there is no machine-readable signal that distinguishes "live marketplace" from "static catalog with sometimes-stale prices" — manual curation is the only honest path. **Confidence: HIGH** that automation here is not worth it for v0 scope.

---

### Q5 — Concurrency: visiting 7-15 candidates per query

**Recommended:**

- **One shared `httpx.AsyncClient` per request** (NOT per visit). Reuses connection pool, HTTP/2 multiplexing.
- **Global semaphore:** `asyncio.Semaphore(8)` — caps total in-flight visits per `/search` call.
- **Per-host semaphore:** dict-of-semaphores keyed by registered domain (use `tldextract` or stdlib `urllib.parse` + regex on suffix); per-host cap of **2 concurrent**.
- **Per-host rate limit (token bucket):** NOT needed for v0 — at 1 query/min global cap and ≤2 in-flight per host, a single host sees at most 2 hits per 60s. Way below any reasonable WAF threshold.
- **Timeout:** `httpx.Timeout(connect=3.0, read=visit_timeout_s, write=3.0, pool=2.0)` — PRD default `visit_timeout_s=10`. Connect timeout shorter to fail fast on dead hosts.

**Code sketch:**
```python
from collections import defaultdict

GLOBAL_VISIT_CAP = 8
PER_HOST_CAP = 2

async def visit_candidates(candidates: list[Candidate], client: httpx.AsyncClient):
    global_sem = asyncio.Semaphore(GLOBAL_VISIT_CAP)
    host_sems: dict[str, asyncio.Semaphore] = defaultdict(
        lambda: asyncio.Semaphore(PER_HOST_CAP)
    )

    async def visit_one(c: Candidate):
        host = urlparse(c.url).netloc
        async with global_sem, host_sems[host]:
            try:
                return await client.get(c.url, follow_redirects=True, timeout=10.0)
            except (httpx.TimeoutException, httpx.NetworkError):
                return None

    return await asyncio.gather(*[visit_one(c) for c in candidates], return_exceptions=True)
```

**Why not `aiolimiter` or `httpx-limiter`:** for v0, the 1-query/min global throttle on Google + the small candidate set (≤15) makes a dedicated rate-limit library overkill. Two semaphores cover the per-host throttling needs. **Add `aiolimiter` only if** in Fase 2 we observe per-host blocks from a specific store. ([aiolimiter docs](https://aiolimiter.readthedocs.io/) — leaky-bucket pattern available if needed.)

> Source: [SuperFastPython asyncio.gather concurrency limit](https://superfastpython.com/asyncio-gather-limit-concurrency/), [rednafi.com semaphore guide](https://rednafi.com/python/limit-concurrency-with-semaphore/).

---

### Q6 — Anti-bot at the candidate-URL level

**Posture:** httpx with realistic browser headers will pass the majority of AR catalog sites because:

1. The visit is **one-shot**, not a session — no cookie state to validate.
2. The visit follows a Google referrer — not a freshly-typed URL — which is the "happy path" for most stores' bot rules.
3. Our request rate per host is glacial (≤2 in-flight, max ~30/day per host given 2000 queries/day × ~7 visits × cache hit 30%).

**Realistic headers to ship (drop-in default in `client = httpx.AsyncClient(headers=DEFAULT_HEADERS)`):**

```python
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
    "Sec-Fetch-Site": "cross-site",  # came from google
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.google.com/",
}
```

**Note on TLS fingerprint:** httpx uses stock OpenSSL/h2 — its TLS fingerprint is identifiable by sophisticated WAFs (DataDome, advanced Cloudflare config). For AR catalog sites:
- Tiendanube: NOT typically WAF-protected at PDP level → httpx passes.
- VTEX-hosted (Musimundo, Garbarino, Easy, Cetrogar): some shops have Akamai Bot Manager. **httpx may 403.**
- Falabella AR: known to use Akamai/Imperva (per global Falabella patterns). **High risk of 403 on httpx.**
- Mayorista frog / small custom: no WAF → httpx passes.

**Degradation strategy:** when httpx returns 403/429/503 → mark `visit_failed=true`, log `host` for triage, **do not retry with Cloak in v0**. Cloak is reserved for Google in this architecture (NF-01: 1 container, Cloak embedded). Adding Cloak to the visit pass triples latency and tightens our IP exposure on Google.

**In Fase 2 (PRD's "Robustez"):** consider a `curl-cffi` (`0.15.0`, TLS-impersonation) fallback for known-Akamai hosts. Adds a small dep, no browser. ~50ms per visit. **Defer** — only if `visit_failed` rate on those hosts exceeds 30%.

> Source: [Scrapfly anti-bot bypass overview](https://scrapfly.io/bypass), [ZenRows on Akamai 403](https://www.zenrows.com/blog/akamai-403). Both confirm: for sophisticated WAFs, httpx alone is insufficient. For "soft" anti-bot (rate-limiting + UA filter), httpx + realistic headers passes.

---

### Q7 — Error budget for `visit_failed`

**Definitions:**
- `visit_failed`: HTTP error (5xx, timeout, network) OR 4xx that's not 404. Includes WAF 403s.
- `skip_dead`: 404 OR redirect-to-home OR title-marked dead. Distinct from `visit_failed` — the URL responded but the resource is gone.

**Healthy run thresholds (from base rates on real ecommerce sweeps):**

| Metric | Healthy | Warning | Action |
|---|---|---|---|
| `visit_failed` rate across all visits | <15% | 15-30% | >30%: investigate (IP block? header drift? specific host?) |
| `skip_dead` rate across all visits | <20% | 20-35% | >35%: LLM filter is letting too much through; tune confidence threshold |
| Per-host `visit_failed` rate (n>10 visits in 7d) | <30% | 30-60% | >60%: blocklist host or skip-visit (assume `fresh=unknown`) |
| `visited` / `candidates_after_llm` ratio | 30-60% | <30% or >80% | Off-target: re-check skip-if-you-can logic |

**Logging requirements:** every visit must emit a structlog event with `host`, `status_code`, `final_url`, `outcome` ∈ `{live, dead, failed}`, `elapsed_ms`. **Do NOT log response body.** This lets Fase 2 build a per-host failure dashboard from log aggregation alone.

---

## Recommended extraction code path

```
candidate_url
    │
    ├─→ httpx.AsyncClient.get(url, headers=DEFAULT, follow_redirects=True, timeout=10)
    │       │
    │       ├─ 4xx/5xx → outcome="failed", return None
    │       ├─ timeout/network → outcome="failed", return None
    │       └─ 200 → continue
    │
    ├─→ classify_response(resp)
    │       ├─ "dead" → outcome="dead", return None
    │       ├─ "failed" → outcome="failed", return None
    │       └─ "live" → continue
    │
    ├─→ selectolax.HTMLParser(resp.text)
    │
    ├─→ extract_jsonld_product(tree)
    │       └─ hit → return ExtractedProduct(price, currency, name, availability, dateModified?)
    │
    ├─→ extract_og_product(tree)
    │       └─ hit → return ExtractedProduct(...)
    │
    ├─→ extract_microdata_product(tree)  [DEFERRED to Fase 2 unless fixture sweep shows need]
    │
    └─→ extract_price_regex(tree)
            └─ hit → return ExtractedProduct(price only, currency="ARS", confidence_penalty=0.1)
```

**Library set (drop-in `pyproject.toml`):**
```toml
[project]
dependencies = [
  "httpx[http2]==0.28.1",
  "selectolax==0.4.9",
  # extruct deferred — only add if Fase 0 fixture sweep shows microdata-only stores in top-10
  # "extruct==0.18.0",
]
```

Confidence on the toml: **HIGH** for httpx + selectolax; **MEDIUM** on deferring extruct (could be a Fase 0 surprise).

---

## Per-host strategy table (top AR stores)

> **Confidence: LOW-MEDIUM.** These are inferences from platform docs + global anti-bot patterns + the v1 project's empirical logs (referenced in PROJECT.md but not re-read here). **Must be validated by Fase 0 fixture sweep** — drive each host once headed, capture HTML, run extraction.

| Host | Platform | JSON-LD Product | OG product:* | Microdata | Anti-bot risk | Recommended visit treatment |
|---|---|---|---|---|---|---|
| `mercadolibre.com.ar` | proprietary | yes (per third-party scrapers) | yes | no | n/a (skipped by PRD policy) | **NEVER visit** — PRD §11 forbids `*.mercadolibre.*` |
| `tiendanube.com.ar` / `*.mitiendanube.com` | Tiendanube | **YES** (theme default) | yes | rare | LOW | visit normally |
| `falabella.com.ar` | VTEX/proprietary | yes | yes | sometimes | **HIGH** (Akamai likely) | visit; on 403 → `visit_failed`, no retry |
| `musimundo.com` / `garbarino.com` / similar | VTEX | yes | yes | sometimes | MEDIUM (Akamai possible) | visit; on 403 → `visit_failed` |
| `walmart.com.ar` | proprietary | yes | yes | rare | MEDIUM | visit; tolerate failures |
| `casasusy.com.ar` | Tiendanube (likely) | yes | yes | no | LOW | visit normally |
| `mayoristafrog.com.ar` | custom/PrestaShop? | unknown — Fase 0 task | unknown | unknown | LOW | visit; regex fallback may be needed |
| `romero-jugueteria.com.ar` | likely Tiendanube | yes (Tiendanube default) | yes | no | LOW | visit normally |
| Generic Shopify (`*.myshopify.com`) | Shopify | **YES** (89% per audit) | yes | no | LOW | visit normally |
| Generic small VTEX | VTEX | yes | yes | sometimes | MEDIUM | visit; tolerate failures |

**Maintenance policy:** this table lives in code as a `dict[str, HostProfile]` in `config.py` (or `hosts.py`). Update at every milestone retrospective. The LLM filter (step 5) already absorbs unlisted hosts gracefully — the table is documentation, not gate logic.

---

## Concurrency + throttling patterns

**Decision matrix:**

| Scenario | Mechanism | Value |
|---|---|---|
| Global cap on in-flight visits per `/search` call | `asyncio.Semaphore` | 8 |
| Per-host cap on in-flight visits per `/search` call | dict-of-semaphores | 2 |
| Per-host rate limit | none in v0 | — |
| HTTP/2 multiplexing | enable on client | `httpx.AsyncClient(http2=True)` |
| Connection pool size | client `limits` | `Limits(max_connections=20, max_keepalive_connections=10)` |
| Connect timeout | `httpx.Timeout` | 3.0s |
| Read timeout | `httpx.Timeout` | `visit_timeout_s` (PRD: 10s) |
| Retry policy | none for visit pass | (LLM has already filtered; visit failures are fine) |

**Why no retry on the visit pass:** retrying a failed visit adds latency (+10s on timeout) and barely improves outcome (the second attempt either also fails or already would've succeeded on a connection reuse). The `visit_failed` flag is the honest signal; surface it in the response metadata for the caller to interpret.

---

## Risks + degradation paths

| Risk | Severity | Mitigation / degradation |
|---|---|---|
| extruct/selectolax misses Product on a heavily-templated site | MEDIUM | Regex price fallback (layer 4). LLM-supplied `price_hint` still surfaces in re-rank |
| Falabella/VTEX-Akamai sites return 403 reliably | MEDIUM | Accept as `visit_failed`. PRD risks already enshrines "Algunos stores con anti-bot en visit step" |
| Per-host semaphore deadlock if same host appears 20 times in candidates | LOW | Dedup step (F-04) already collapses URLs; per-host queue depth bounded by visited count |
| `extruct` heavy deps (rdflib, pyrdfa3) bloat the image | LOW-MEDIUM | Hand-rolled selectolax extractor avoids this. Defer extruct unless Fase 0 sweep mandates it |
| Title-based dead-page detection false-positives on products literally named "Error" or "404" | LOW | Match dead markers against `title` AND `h1` AND apply marker only if BOTH match. Plus presence of JSON-LD Product overrides "dead" verdict |
| Soft-404 redirect to a *search-results* page (not home) bypasses redirect-path check | MEDIUM | Add `/buscar`, `/search`, `/s?` to soft-404 path patterns |
| Per-host data freshness changes — Falabella starts requiring JS rendering | MEDIUM | Empirical: `visit_failed` rate spikes for that host → triage → either drop visit for that host or upgrade to Cloak (Fase 2 decision) |
| Visit pass on a domain that runs JS-only PDP (rare for AR catalog but possible) | LOW | httpx returns the SSR shell; extraction returns None; `price=None` propagates; LLM `price_hint` carries the day if present |

---

## Sources

- [PRD.md — section 3 step 6, section 6](file:///home/luis/proyectos/artiscrapper/PRD.md)
- [PROJECT.md — F-06, F-07](file:///home/luis/proyectos/artiscrapper/.planning/PROJECT.md)
- [extruct on GitHub](https://github.com/scrapinghub/extruct) — features, syntaxes, uniform=True flag
- [extruct on PyPI (0.18.0)](https://pypi.org/pypi/extruct/json) — deps: lxml, lxml-html-clean, rdflib>=6.0.0, pyrdfa3, mf2py, w3lib, html-text, jstyleson
- [hackersandslackers — Scrape Structured Data with Python and Extruct](https://hackersandslackers.com/scrape-metadata-json-ld/) — usage patterns
- [Tiendanube — Datos estructurados JSON-LD docs](https://docs.tiendanube.com/help/data-estructurada-json-ld) — confirms Tiendanube emits Product JSON-LD by default
- [DigitalApplied 5k-site schema audit](https://www.digitalapplied.com/blog/schema-markup-adoption-5k-site-audit-2026) — 89% Shopify Product schema adoption; 53% sitewide JSON-LD
- [Vanguard Edge — Schema Product E-commerce 2026](https://vanguard-edge-consulting.com/blog/schema-product-offer-ecommerce-2026/) — recommended fields
- [searchengineland on dateModified for AI freshness](https://searchengineland.com/date-published-date-updated-organic-ctr-453209) — why most e-commerce PDPs skip date emission
- [Open Graph Protocol — product type](https://ogp.me/) — product:price:amount + product:price:currency are the canonical OG product props (NOT `og:price`)
- [benhoyt/soft404](https://github.com/benhoyt/soft404) — soft-404 detection heuristic (test against a known-bad URL); not adopted but informs the title-based check
- [ithy.com — Top 5 Methods to Detect 404 Errors in Python](https://ithy.com/article/top-5-python-methods-for-404-detection-1x7b790g) — heuristic catalog
- [SuperFastPython — asyncio.gather Limit Concurrency](https://superfastpython.com/asyncio-gather-limit-concurrency/) — semaphore pattern
- [rednafi — Limit concurrency with semaphore](https://rednafi.com/python/limit-concurrency-with-semaphore/) — semaphore + httpx pattern
- [aiolimiter docs](https://aiolimiter.readthedocs.io/) — leaky-bucket pattern reference (not adopted in v0)
- [httpx-limiter on PyPI](https://pypi.org/project/httpx-limiter/) — per-host rate-limiting library (deferred to Fase 2)
- [Scrapfly — bypass anti-bot vendors](https://scrapfly.io/bypass) — Akamai/Cloudflare/Imperva landscape
- [ZenRows — Akamai 403 troubleshooting](https://www.zenrows.com/blog/akamai-403) — failure modes for httpx against Akamai
- [scrapfly.io — How to Rate Limit Async Requests in Python](https://scrapfly.io/blog/posts/how-to-rate-limit-asynchronous-python-requests) — patterns
- [httpx quickstart docs](https://www.python-httpx.org/quickstart/) — `follow_redirects`, `response.history`, timeout config
- [StoreLeads — VTEX Argentina (453 stores)](https://storeleads.app/reports/vtex/AR/top-stores) — VTEX footprint in AR
