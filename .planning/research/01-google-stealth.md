# Research 01 — Google Stealth Strategy (Cloakbrowser + SERP parser)

**Scope:** artiscrapper v0 — single FastAPI container, sync `/search`, 500–2000 q/day from 1 IP, Cloak as only browser.
**Date:** 2026-06-01
**Researcher:** GSD research agent (focused brief)

---

## Verdict (per focus question, confidence-tagged)

| # | Question | Verdict | Confidence |
|---|---|---|---|
| 1 | Cloak `0.3.28` + `chromium-v146.0.7680.177.4` still the right pin? | **NO — bump to `0.3.31` + `chromium-v146.0.7680.177.5`** (both published in last 10 days, no breaking changes; the `.5` patch is a stealth refresh, exactly the kind of pin update OPS-09 mandates). | **HIGH** |
| 2 | Cloak embedded in FastAPI container vs separate `cloakserve` service? | **Embedded is correct for v0**, with one Browser instance as a FastAPI singleton and **per-request ephemeral `new_context()`** (NOT `launch_persistent_context`). Budget ~500 MB resident for Chromium + ~50–100 MB per page. At 1 q/min the concurrency is effectively 1; a small `asyncio.Semaphore(2)` is enough headroom. | **HIGH** |
| 3 | Google SERP parser stability — how much will `tF2Cxc`/`Ez5pwe`/`MjjYud` drift? | **Drift is real and ~quarterly for obfuscated classes.** Build a **multi-selector cascade** with an h3+ancestor fallback, alert on parse-rate drop. The PRD's three selectors are correct *as of today* but cannot be the only path. | **HIGH** |
| 4 | Google anti-bot triggers at 1 q/min from 1 datacenter IP with Cloak? | **MEDIUM risk — workable but not free.** Empirical citation: ~100 req/h per IP is the commonly-cited soft cap; at our 1 q/min × 2 fetches = 2/min = 120/h we are *just over the floor*. Cache (target 30 % hit) and weekly canary keep us live. Watch for `/sorry/index?continue=` redirects and `g-recaptcha` markup in the response — those are the kill signals. | **MEDIUM** |
| 5 | AR locale params beyond `hl=es&gl=ar`? | **YES — add `pws=0` always, drop `num` (deprecated Sep 2025), keep `safe=off`.** `udm` not needed for organic+carousel queries. `tbm=shop`/`udm=28` would change the page shape entirely — *do not use* for our SERP shape. | **HIGH** |

---

## Findings

### Q1 — Cloakbrowser & Chromium pin (HIGH confidence)

Verified directly against PyPI + GitHub API on 2026-06-01:

| Artifact | Old pin (PRD) | Latest available | Decision |
|---|---|---|---|
| `cloakbrowser` (PyPI) | `0.3.28` (2026-04-28) | **`0.3.31`** (2026-05-26) | Bump |
| Chromium binary (GitHub release tag) | `chromium-v146.0.7680.177.4` (2026-04-28) | **`chromium-v146.0.7680.177.5`** (2026-05-21) | Bump |
| `playwright` (PyPI) | `1.59.0` | `1.59.0` (transitive ≥1.40) | Hold |

- Release cadence is ~2–3 weeks per `chromium-v146.0.7680.177.x`. The `.5` is a stealth-patch refresh (no breaking surface).
- PyPI `0.3.31` released today-ish (2026-05-26) — `requires_python>=3.9`, deps `httpx>=0.24`, `playwright>=1.40`. No new required deps vs `0.3.28`. Optional extras unchanged (`[geoip]`, `[patchright]`, `[serve]`, `[dev]`).
- Repo activity: `https://api.github.com/repos/CloakHQ/CloakBrowser` shows last push `2026-05-15…2026-05-21`, no archive flag, 91 open issues — alive.
- Known live bugs as of today (from `…/issues?state=open&sort=updated`, top of stack):
  - **#331** — `launchPersistentContext` triggers Google "suspicious activity" CAPTCHA. *Affects us directly.* Mitigation: use `browser.new_context()` (ephemeral) per request, not `launch_persistent_context`. See Q2.
  - **#336** / **#330** — FingerprintJS / WebGL signature still detectable in some matrices. Not relevant to Google (Google doesn't ship FingerprintJS at the SERP), but flag if we ever visit a store with one.
  - **#332** — "hardcoded binary version" — informational; the version-pinning pattern we already use side-steps this.
  - **#208** — Servicepipe Cybert antibot defeats Cloak. Not relevant (Google doesn't use Servicepipe).
- Verdict: bump pin, keep pin discipline (exact `==`, release-tag pin in Dockerfile, weekly OPS-09 triage).

### Q2 — Embedded vs separate `cloakserve` (HIGH confidence)

**Decision: embedded, singleton Browser, per-request `new_context()`.**

Cloakbrowser exposes three deployment shapes:

1. `launch()` / `launch_async()` — short-lived process-local browser. Wrong for an HTTP service (10–20 s of startup per request).
2. `launch_persistent_context(user_data_dir)` — keeps profile across launches. **Banned by issue #331 for Google work** (CAPTCHA every request).
3. `cloakserve` (CDP server in a separate container) — for multi-client setups; redundant for 1 service / 1 process.

The right shape for v0 is option **1 turned into a singleton**: start Cloak in `lifespan` once at FastAPI boot, keep the `Browser` handle for the process lifetime, open a fresh `BrowserContext` per request, close it after.

Why ephemeral contexts not persistent ones:

- Issue #331 (open, 2026-05-30, 7 comments) is unambiguous: persistent context → Google `/sorry/index` challenge; ephemeral → fine.
- Ephemeral contexts also reset cookies, so Google sees each query as a "first-time visitor" — exactly the surface we want.
- Memory cost of an ephemeral context is the per-page cost (~50–100 MB), released on close.

Resource budget (from Cloak docs + Playwright general):

| Item | RSS |
|---|---|
| Singleton Chromium browser (idle, 0 pages) | ~190 MB (Cloak docs) |
| Per ephemeral context + 1 page | ~50–100 MB |
| 2 parallel pages (URL A + URL B) | ~280–380 MB peak (matches Cloak's "~280 MB with 3 tabs" benchmark) |
| Worst case in our container | ~**500 MB resident** including FastAPI + selectolax + sqlite |

Concurrency: PRD says 1 q/min rate-limited inside the app. Even if two clients hit `/search` at once, we want them serialized at the Google fetch step, not at the FastAPI handler. Use **one `asyncio.Semaphore(1)` around the Google fetch block** to enforce that. The two parallel fetches (`q` and `q +mercadolibre`) happen *inside* a single semaphore acquisition.

Startup pattern (recommended):

```python
# app/browser.py
from contextlib import asynccontextmanager
from cloakbrowser import async_playwright  # cloak exposes the same factory

class CloakHandle:
    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._sema = asyncio.Semaphore(1)  # global Google rate-limit serializer

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    @asynccontextmanager
    async def session(self):
        """One ephemeral context per request — NEVER persistent (issue #331)."""
        async with self._sema:
            ctx = await self._browser.new_context(
                locale="es-AR",
                timezone_id="America/Argentina/Buenos_Aires",
                viewport={"width": 1366, "height": 768},
                # NO storage_state, NO user_data_dir
            )
            try:
                yield ctx
            finally:
                await ctx.close()

cloak = CloakHandle()

# app/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    await cloak.start()
    yield
    await cloak.stop()
```

Why **not** `cloakserve` as a separate container at v0:
- Adds an HTTP hop, a second container, and another failure mode (was painful in v1 — `browser-pool-cloak` outages cascaded).
- The PRD explicitly says "1 container Docker" and "Cloak embebido vía Playwright en el mismo proceso".
- Buys nothing for our throughput (1/min).

### Q3 — Google SERP parser stability (HIGH confidence on drift, MEDIUM on exact cadence)

Several converging community signals:

- "Selectors that worked reliably in 2024 have broken and required updates in 2026" — Scrapfly, RoundProxies, ScraperAPI all repeat the same point.
- Obfuscated classes (`MjjYud`, `tF2Cxc`, `Ez5pwe`, `VwiC3b`) rotate **roughly every few months**. Stable classes (`yuRUbf` for link wrapper, `LC20lb`/`DKV0Md` on the `<h3>` title) have lasted multiple years.
- The PRD's three selectors (`div.tF2Cxc`, `div.Ez5pwe`, `div.MjjYud`) are **correct as of v1's last test** — but already considered "high-volatility" by the community. Building only on them = guaranteed Phase-2 emergency.
- Most-cited 2026 fallback strategy: **multi-selector cascade**, plus an **h3-anchored generic extractor** as the last resort (find every `<h3>` whose ancestor wraps an `<a href>` to an external site, treat as organic candidate). This degrades gracefully when Google scrambles obfuscated wrappers but keeps the `<h3>` skeleton.

Practical cascade for organic + carousel:

```python
ORGANIC_SELECTORS = [
    "div.MjjYud div.tF2Cxc",       # 2024-2026 primary
    "div.MjjYud",                  # 2025+ wrapper as fallback
    "div.g",                       # legacy but still serves on some experiments
    "div[data-sokoban-container]", # 2025-2026 experimental wrapper
    "div[data-snc]",               # observed in mobile variants
]
CAROUSEL_SELECTORS = [
    "div.Ez5pwe",                  # current popular-products carousel
    "g-scrolling-carousel div[role='listitem']",  # generic ARIA structure
    "div[data-attrid*='shopping']",
]
H3_LAST_RESORT = "h3"  # iterate, climb to nearest <a href> with an external host
```

Algorithm: for each selector in `ORGANIC_SELECTORS`, parse; if zero hits, advance. If all five return zero, log `parse.cascade.exhausted` with a hash of the raw HTML, fall back to the h3 walk. Persist `raw_serp_html` so a human (or replay test) can confirm the new selector after the next break.

**Alerting:** track per-fetch `organic_count` and `carousel_count`. If 7-day rolling average drops > 50 % week-over-week → page on Slack. This is cheaper than maintaining hand-coded selector versions.

No public community fixture repo currently maintains these (checked SerpApi, Scrapfly, RoundProxies — all gate it behind their paid SERP APIs). We have to be our own fixture: snapshot `raw_serp_html` on every fetch into sqlite for forensics (PRD §6 already requires this).

### Q4 — Google anti-bot at our scale (MEDIUM confidence)

What triggers `/sorry/index?continue=...`:

- **Volume**: ~100 req/h per IP is the most commonly cited soft cap. Our planned **2 fetches per query × ~1 q/min = 120/h** is *just at the threshold*. The 30 % cache hit (PRD success criterion) drops this to ~84/h — under the line.
- **Fingerprint instability**: Stock Playwright fails by request #5 because of TLS / `navigator.webdriver`. Cloak's C++-level patches push that limit out by ~30×. Cloak's reCAPTCHA v3 score is ~0.9 (vs ~0.1 for stock Playwright) per CloakHQ's own demo, with corroboration in the andrew.ooo independent review.
- **Persistent profile** → bigger detector signal (issue #331). We're explicitly using ephemeral contexts, so this risk is mitigated.
- **Header / locale consistency**: a request claiming `hl=es&gl=ar` but with an Accept-Language of `en-US,en;q=0.9` is a red flag. Playwright honors `BrowserContext.locale` for `Accept-Language`, but the IP geo doesn't match (we're on a VPS, likely DE/US ASN). At our scale this is *probably* fine — Google permits cross-geo `gl` overrides for travelers and SEO tools — but it's a real second-order risk.
- **Referer** & **cookie continuity**: clean ephemeral context = no cookies = "first visit". This is *less* suspicious than a stale long-lived session, not more.
- **Datacenter ASN**: the VPS IP is datacenter, not residential. The mitigation in PRD is "cache + 1/min" not "proxy". Acceptable risk for v0; degrade to "challenge detected, return 503 with hint" if it breaks.

Detection in code:

```python
async def _detect_block(page) -> str | None:
    url = page.url
    if "/sorry/index" in url or "/sorry/?continue=" in url:
        return "sorry_index"
    title = (await page.title() or "").lower()
    if "before you continue" in title or "unusual traffic" in title:
        return "unusual_traffic"
    # Cheap content sniff — don't log it, just match
    content = await page.content()
    if "g-recaptcha" in content or "id=\"captcha-form\"" in content:
        return "recaptcha"
    return None
```

When `_detect_block` fires:
1. Increment `google_block_total{reason=...}` Prom counter.
2. Skip cache write (don't poison cache with a challenge page).
3. Return `HTTP 503` with `Retry-After: 900` (15 min, lower bound of typical IP cooldown).
4. Structured log `google.fetch.blocked reason=sorry_index query_hash=<hash>` — never log the query string.

Expected empirical block rate at our scale: **under 5 %/day** with cache + 1/min + ephemeral contexts + Cloak. This is a gut estimate from community reports; we won't know until Fase 0 spike. Track and adjust the rate-limit if blocks > 1 %/day for two consecutive days.

### Q5 — AR locale tactics (HIGH confidence)

Working parameters as of 2026-06-01:

| Param | Value | Effect | Status |
|---|---|---|---|
| `q` | URL-encoded query | the query | required |
| `hl` | `es` | UI language (drives `Accept-Language` echo, currency formatting) | required |
| `gl` | `ar` | geo-bias of results — surface AR stores | required |
| `pws` | `0` | disable personalization (consistent results across runs) | **required for cache reproducibility** |
| `safe` | `off` | don't filter; we want product/aftermarket auto parts | recommended |
| `num` | — | **deprecated since Sep 2025**; ignored by Google | **DO NOT SET** |
| `start` | `0` | pagination offset (10/page now) | not needed for v0 — first page is enough |
| `tbm`/`udm` | — | switch vertical (shopping, news…); changes page shape | **DO NOT SET** — our parser targets organic+carousel on the *web* SERP |
| `lr` / `cr` | — | language/country restrict; redundant with `hl`/`gl` and noisy | skip |
| `ie` / `oe` | UTF-8 default | no-op | skip |

Built URL pattern:

```python
def build_serp_url(query: str, *, meli: bool = False) -> str:
    q = quote_plus(f"{query} mercadolibre" if meli else query)
    return (
        "https://www.google.com/search"
        f"?q={q}&hl=es&gl=ar&pws=0&safe=off"
    )
```

Notes:
- `udm=28` returns Google Shopping vertical — different markup entirely, different cards, no `Ez5pwe`. Out of scope; revisit only if PRD adds a "shopping mode".
- For *future* paginated cases: replace `num=100` with looped `start=0/10/20/...` (Sep 2025 change). Not needed at v0 — PRD wants top ~15 results, one page covers it.
- The `+mercadolibre` query (PRD's URL B) does NOT need `site:mercadolibre.com.ar` — Google's regular ranker already promotes MELI cards. Adding `site:` would actually hide the carousel; do not add it.

---

## Recommended pattern code

### Cloak singleton + ephemeral context

```python
# app/browser.py
import asyncio
from contextlib import asynccontextmanager
from cloakbrowser import async_playwright

class CloakSingleton:
    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._google_sema = asyncio.Semaphore(1)  # enforce 1 in-flight google fetch

    async def start(self):
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    @asynccontextmanager
    async def google_context(self):
        """Ephemeral, locale-pinned, rate-limited."""
        async with self._google_sema:
            ctx = await self._browser.new_context(
                locale="es-AR",
                timezone_id="America/Argentina/Buenos_Aires",
                viewport={"width": 1366, "height": 768},
            )
            try:
                yield ctx
            finally:
                await ctx.close()
```

### Parallel fetch with block detection

```python
async def fetch_serp(cloak: CloakSingleton, url: str) -> tuple[str, str | None]:
    """Returns (html, block_reason | None). Caller persists raw_serp_html."""
    async with cloak.google_context() as ctx:
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        reason = await _detect_block(page)
        html = await page.content()
        await page.close()
        return html, reason
```

### Parser cascade

```python
from selectolax.parser import HTMLParser

ORGANIC_SELECTORS = [
    "div.MjjYud div.tF2Cxc",
    "div.MjjYud",
    "div.g",
    "div[data-sokoban-container]",
    "div[data-snc]",
]

def parse_organic(html: str) -> list[dict]:
    tree = HTMLParser(html)
    for sel in ORGANIC_SELECTORS:
        nodes = tree.css(sel)
        if nodes:
            results = [_extract_organic(n) for n in nodes]
            results = [r for r in results if r]
            if results:
                return results
    # Last resort: h3 walk
    return _extract_by_h3(tree)

def _extract_organic(node) -> dict | None:
    h3 = node.css_first("h3")
    a = node.css_first("a")
    if not (h3 and a and a.attributes.get("href", "").startswith("http")):
        return None
    snippet = node.css_first(".VwiC3b") or node.css_first("div[data-sncf]")
    return {
        "title": h3.text(strip=True),
        "url": a.attributes["href"],
        "snippet": snippet.text(strip=True) if snippet else None,
    }

def _extract_by_h3(tree) -> list[dict]:
    """Generic fallback: every h3 inside an <a href> outside google.com."""
    out = []
    for h3 in tree.css("h3"):
        a = h3.parent
        while a and a.tag != "a":
            a = a.parent
        if not a:
            continue
        href = a.attributes.get("href", "")
        if not href.startswith("http") or "google.com" in href:
            continue
        out.append({"title": h3.text(strip=True), "url": href, "snippet": None})
    return out
```

### Block detection

```python
async def _detect_block(page) -> str | None:
    url = page.url or ""
    if "/sorry/" in url:
        return "sorry_redirect"
    content = (await page.content()) or ""
    if "g-recaptcha" in content or 'id="captcha-form"' in content:
        return "captcha_form"
    if "unusual traffic" in content.lower():
        return "unusual_traffic"
    return None
```

---

## Risks for our specific scope

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Datacenter IP gets flagged after ~2 weeks of operation | Medium | Service degrades to 503s | Cache TTL stays at 24 h (PRD); add weekly headed canary; document VPS-modem-reset escape hatch |
| Google rotates `tF2Cxc` / `Ez5pwe` mid-quarter | High | Parse rate drops, products empty | Multi-selector cascade + h3 fallback + `parse.cascade.exhausted` alarm + raw_serp_html in cache for replay |
| Cloak `0.3.31`→`0.3.32` ships a fingerprint regression | Medium | New blocks appear suddenly | OPS-09 weekly triage; pin exact version; run canary against known-good fixture *before* deploying browser-engine bumps |
| Persistent context accidentally used (copy-paste from old code) | Medium | Per-request CAPTCHA spike | Code review check; static lint rule banning `launch_persistent_context` import in this repo |
| Memory creep over weeks due to Playwright `_objects` HashMap leak | Low at our scale | Container OOM | Recycle browser process every N requests (e.g., 500) or on a 6 h timer |
| `+mercadolibre` query returns mostly the carousel; carousel selector breaks → MELI yield drops to ~zero | Medium | Sánchez's key use case degrades silently | Track per-source counts; alarm on `carousel_count == 0 AND meli_links == 0` for >1 day |

---

## What NOT to do

- **Do NOT use `cloakbrowser.launch_persistent_context`** for Google queries. Open issue #331 documents per-request CAPTCHA. Stay ephemeral.
- **Do NOT add `num=100`** (or any `num`) — dead since Sep 2025, silently ignored.
- **Do NOT add `tbm=shop` or `udm=28`** — that's the Google Shopping vertical, different DOM, our parser would return zero.
- **Do NOT use stock Playwright** — fingerprint flag in <5 requests, MELI-style auto-block.
- **Do NOT auto-bump Chromium binary tag in CI** — must be a human-reviewed PR with canary green (CLAUDE.md OPS-09).
- **Do NOT log raw SERP HTML or query strings** in standard log stream — PRD §6 + structlog field whitelist. Persist HTML only in sqlite cache.
- **Do NOT skip the cache lookup** — even on Fase 0 spike. Single Google fetch on a "fresh" query without cache → muscle memory you'll regret.
- **Do NOT run `cloakserve` as a sidecar** for v0. PRD says one container; redundant hop & failure mode.
- **Do NOT trust the PRD's 3 selectors as permanent** — they will rotate; ship the cascade now, not on the second outage.
- **Do NOT add `site:mercadolibre.com.ar`** to URL B — hides the carousel cards we want.

---

## Sources

Verification & primary docs (HIGH confidence — direct API hits):

- `https://api.github.com/repos/CloakHQ/CloakBrowser/releases/latest` — `chromium-v146.0.7680.177.5`, published 2026-05-21 (verified 2026-06-01)
- `https://api.github.com/repos/CloakHQ/CloakBrowser/releases?per_page=8` — release cadence ~10–20 days per stealth patch
- `https://pypi.org/pypi/cloakbrowser/json` — version `0.3.31`, uploaded 2026-05-26
- `https://api.github.com/repos/CloakHQ/CloakBrowser/issues?state=open&sort=updated` — current open issues incl. #331 (persistent-context Google detect), #320, #208

Cloakbrowser docs & reviews (HIGH/MEDIUM):
- `https://github.com/CloakHQ/CloakBrowser` — official README, usage patterns, Docker image `cloakhq/cloakbrowser`, binary ~200 MB, RAM ~190 MB idle / ~280 MB 3 tabs
- `https://github.com/CloakHQ/CloakBrowser/issues/331` — persistent-context Google CAPTCHA bug (open, 2026-05-30)
- `https://andrew.ooo/posts/cloakbrowser-stealth-chromium-playwright-replacement-review/` — independent review confirming reCAPTCHA v3 ≈ 0.9; mentions pin-the-binary discipline
- `https://aitoolly.com/ai-news/article/2026-05-21-cloakbrowser-the-stealth-chromium-fork-achieving-100-success-in-bot-detection-tests` — release-day coverage of `v146.0.7680.177.5`

Google SERP scraping (MEDIUM — community consensus, not vendor-neutral):
- `https://scrapfly.io/blog/posts/how-to-scrape-google` — selector drift in 2026, XPath / data-attribute fallback
- `https://roundproxies.com/blog/scrape-google-search-results/` — multi-selector cascade (`.g`, `.yuRUbf`, `.VwiC3b`, `.Gx5Zad`, `.st`)
- `https://scrapebadger.com/blog/how-to-scrape-google-search-results-without-getting-blocked-2026-complete-guide` — "~100 req/h per IP" soft cap citation
- `https://www.scraperapi.com/blog/css-selectors-cheat-sheet/` — confirms `tF2Cxc`/`MjjYud`/`VwiC3b` rotate every few months

Google URL parameters (HIGH):
- `https://brightdata.com/blog/web-data/google-search-url-parameters` — 2026 full param list; `num` deprecation, `pws=0`, `gl`/`hl` semantics
- `https://locomotive.agency/blog/google-removes-num100-parameter-what-this-means-for-your-website/` — Sep 12–14 2025 `num` removal confirmation
- `https://serpapi.com/blog/every-google-udm-in-the-world/` — `udm` parameter index; `udm=28` = shopping
- `https://intender.com.au/full-list-of-working-google-search-query-parameters-operators/` — `tbm` vs `udm` overlap

Playwright lifecycle (MEDIUM):
- `https://github.com/microsoft/playwright-python/issues/286` — BrowserContext memory leak when reused, supports "ephemeral context per request" recommendation
- `https://playwright.dev/docs/api/class-browsercontext` — official lifecycle API

Project memory (HIGH, internal):
- v1 `project_meli_block_diagnostic.md` — `/gz/account-verification` redirect confirms MELI direct path is dead; reinforces "Google-as-discovery" strategy.
- v1 `feedback_compose_build_recreate.md` — operational lesson for the Docker-level build/restart discipline that applies here.
