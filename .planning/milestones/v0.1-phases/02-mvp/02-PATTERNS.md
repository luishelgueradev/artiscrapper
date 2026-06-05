# Phase 2: MVP — Pattern Map

**Mapped:** 2026-06-02
**Files analyzed:** 23 new/modified files
**Analogs found:** 17 / 23 (6 NO-ANALOG — no spike-script equivalent; RESEARCH.md Pattern N is canonical)

---

## Greenfield Context

No `src/` production code exists yet. The codebase has only `scripts/spike/` throwaway scripts from Phase 1 and captured fixtures under `tests/fixtures/`. Every analog below is either (a) a Phase 1 spike script under `scripts/spike/` or (b) "NO-ANALOG — use 02-RESEARCH.md Pattern N verbatim."

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/artiscrapper/main.py` | FastAPI app + lifespan + health routes | request-response + background task | NO-ANALOG (no HTTP server in Phase 1) | no-analog — use RESEARCH.md Pattern 1 + 11 |
| `src/artiscrapper/config.py` | pydantic-settings Settings | config | NO-ANALOG | no-analog — use RESEARCH.md §Arch |
| `src/artiscrapper/models.py` | Pydantic request/response models | transform | `scripts/spike/labels.py` | role-match (Pydantic schema) |
| `src/artiscrapper/browser.py` | Cloak singleton + fetch_serp + _detect_block | browser → file-I/O | `scripts/spike/02_cloak_smoke.py` | exact (browser lifecycle) |
| `src/artiscrapper/rate_limit.py` | GoogleRateLimiter (Semaphore + timestamp) | event-driven | NO-ANALOG | no-analog — use RESEARCH.md Pattern 1 (GoogleRateLimiter section) |
| `src/artiscrapper/search.py` | build_serp_url + parse_serp + canonicalize + dedupe + blocklist + rerank | transform | `scripts/spike/08_extruct_classifier.py` (parser functions) | role-match (HTML parsing + cascade) |
| `src/artiscrapper/llm.py` | LLMVerdict + classify_candidate + SYSTEM_PROMPT + should_keep | request-response | `scripts/spike/05_router_probe.py` | role-match (httpx + OpenAI-compat calls) |
| `src/artiscrapper/visit.py` | visit_candidates + classify_response + extract_product | request-response + transform | `scripts/spike/07_falabella_403.py` (httpx) + `scripts/spike/08_extruct_classifier.py` (extractor) | role-match |
| `src/artiscrapper/cache.py` | aiosqlite WAL + gzip BLOBs + lazy TTL + prune + checkpoint | CRUD | NO-ANALOG (no sqlite in spike) | no-analog — use RESEARCH.md Pattern 2 |
| `src/artiscrapper/logging_setup.py` | structlog + asgi-correlation-id | observability | NO-ANALOG | no-analog — use RESEARCH.md Pattern 3 |
| `src/artiscrapper/metrics.py` | Inline counters (pre-Prometheus) | observability | NO-ANALOG | no-analog — use RESEARCH.md Pattern 13 |
| `Dockerfile` | Multi-stage cloakbrowser base + libnspr4/libnss3 + tini | deploy | NO-ANALOG | no-analog — use RESEARCH.md Pattern 12 |
| `compose.yml` | Dev local with sqlite bind-mount | deploy | NO-ANALOG | no-analog — use RESEARCH.md Pattern 12 |
| `pyproject.toml` | deps + pytest + ruff + mypy | config | `pyproject.toml.spike` | partial-match (dep list only; structure differs) |
| `tests/conftest.py` | Shared fixtures (tmp_db, mock_browser, mock_app_state) | test fixture | NO-ANALOG | no-analog — use RESEARCH.md Pattern 1 test override |
| `tests/test_parser.py` | Unit tests against serp fixtures | unit test | NO-ANALOG | no-analog — test structure from RESEARCH.md §Validation |
| `tests/test_llm.py` | Integration tests with respx mock | integration test | `scripts/spike/05_router_probe.py` (call shape) | role-match |
| `tests/test_visit.py` | classify_response + extractor unit tests | unit test | `scripts/spike/08_extruct_classifier.py` | role-match |
| `tests/test_cache.py` | Cache hit/miss + TTL + gzip roundtrip | integration test | NO-ANALOG | no-analog — use RESEARCH.md Pattern 2 |
| `tests/test_health.py` | /health + /health/deep shape tests | integration test | NO-ANALOG | no-analog — use RESEARCH.md Pattern 11 |
| `tests/test_footguns.py` | D2 + D6 + D8 invariant assertions | unit test | NO-ANALOG | no-analog — use RESEARCH.md Pattern 10 |
| `tests/test_e2e.py` | Live dev-box /search e2e | e2e test | NO-ANALOG | no-analog — use RESEARCH.md §Validation |
| `.github/workflows/ci.yml` | ruff + mypy + pytest + uvloop assertion | CI | NO-ANALOG | no-analog — use RESEARCH.md Pattern 10 |

---

## Pattern Assignments by Plan

### PLAN 02-01 — Core Pipeline

---

#### `src/artiscrapper/main.py` (FastAPI app + lifespan + health routes)

**Analog:** NO-ANALOG (Phase 1 produced no HTTP server)
**Canonical reference:** `02-RESEARCH.md` Pattern 1 (lines 287-402) + Pattern 11 (lines 1233-1293)

**Imports pattern** (RESEARCH.md lines 289-303):
```python
import asyncio, gzip, hashlib, time
from contextlib import asynccontextmanager
import aiosqlite
import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from cloakbrowser import launch_async  # NOT async_playwright — Phase 1 confirmed this
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from .logging_setup import configure_logging
from .config import settings
from .cache import init_schema, PRAGMAS, prune_loop
from .rate_limit import GoogleRateLimiter

log = structlog.get_logger()
```

**Lifespan pattern** (RESEARCH.md lines 352-402):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(json_logs=settings.LOG_JSON, level=settings.LOG_LEVEL)
    log.info("boot_start", version=settings.VERSION)

    # 1. sqlite cache
    app.state.cache = await aiosqlite.connect(settings.CACHE_DB_PATH)
    for pragma in PRAGMAS:
        await app.state.cache.execute(pragma)
    await app.state.cache.commit()
    await init_schema(app.state.cache)

    # 2. Cloak browser
    app.state.browser = await launch_async(headless=settings.HEADLESS)
    app.state.browser_uses = 0

    # 3. Rate limiter
    app.state.rate_limit = GoogleRateLimiter(
        min_interval_s=settings.GOOGLE_MIN_INTERVAL_S
    )

    # 4. Background tasks
    tasks = [
        asyncio.create_task(_recycle_browser_loop(app), name="browser_recycle"),
        asyncio.create_task(prune_loop(app.state.cache), name="cache_prune"),
    ]
    log.info("boot_done")
    try:
        yield
    finally:
        log.info("shutdown_start")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await app.state.cache.close()
        try:
            await app.state.browser.close()
        except Exception:
            pass
        log.info("shutdown_done")

app = FastAPI(
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
    title="artiscrapper",
    version=settings.VERSION,
)
app.add_middleware(CorrelationIdMiddleware)
```

**SIGSTOP heartbeat recycle loop** (RESEARCH.md lines 305-350 — CRITICAL Phase 1 NEEDS-PIVOT):
```python
async def _recycle_browser_loop(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(10)  # heartbeat interval (10s per SPIKE.md §Risks)
        browser = app.state.browser
        # Primary check: is_connected() catches SIGKILL
        if not browser.is_connected():
            log.warning("browser_dead_sigkill")
            app.state.browser = await launch_async(headless=settings.HEADLESS)
            app.state.browser_uses = 0
            try:
                await browser.close()
            except Exception:
                pass
            continue
        # Secondary heartbeat: catches SIGSTOP (is_connected() stays True for SIGSTOP)
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await asyncio.wait_for(page.evaluate("1"), timeout=5.0)
            await page.close()
            await ctx.close()
        except Exception as exc:
            log.warning("browser_heartbeat_failed", error=str(type(exc).__name__))
            app.state.browser = await launch_async(headless=settings.HEADLESS)
            app.state.browser_uses = 0
            try:
                await browser.close()
            except Exception:
                pass
            continue
        # Recycle after N cold fetches
        if app.state.browser_uses >= settings.BROWSER_RECYCLE_AFTER:
            log.info("browser_recycle_start", uses=app.state.browser_uses)
            old = app.state.browser
            app.state.browser = await launch_async(headless=settings.HEADLESS)
            app.state.browser_uses = 0
            try:
                await old.close()
            except Exception:
                pass
            log.info("browser_recycle_done")
```

**Critical pitfalls for this file:**
- `CorrelationIdMiddleware` MUST be added AFTER the app is created (it becomes the outermost middleware).
- `configure_logging()` MUST be called at the top of lifespan, before any `log.info()`.
- D6 foot-gun: uvicorn CMD in Dockerfile must use `--loop asyncio --workers 1`.

---

#### `src/artiscrapper/config.py` (pydantic-settings Settings)

**Analog:** NO-ANALOG
**Canonical reference:** 02-RESEARCH.md §Architectural Responsibility Map (line 108) + implied env vars from Pattern 1

**Settings pattern** (inferred from RESEARCH.md references to `settings.*`):
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    VERSION: str = "0.1.0"
    CACHE_DB_PATH: str = "/app/cache.db"
    HEADLESS: bool = True
    GOOGLE_MIN_INTERVAL_S: int = 60
    BROWSER_RECYCLE_AFTER: int = 200
    LLM_ROUTER_URL: str = "http://127.0.0.1:3210"
    LLM_ROUTER_BEARER_TOKEN: str  # no default — must be set; startup fails without it
    LLM_CONCURRENCY: int = 4      # empirically confirmed Phase 1
    LOG_JSON: bool = True
    LOG_LEVEL: str = "INFO"

settings = Settings()
```

**Critical:** `LLM_ROUTER_BEARER_TOKEN` has NO default. Startup MUST fail with a clear message if absent (RESEARCH.md §Environment — "code must fail at startup with a clear message").

---

#### `src/artiscrapper/models.py` (Pydantic request/response models)

**Analog:** `scripts/spike/labels.py` (lines 1-33) — closest existing Pydantic schema in repo.

**Analog pattern to mirror** (`scripts/spike/labels.py` lines 8-33):
```python
from pydantic import BaseModel, Field
from typing import Literal

class CandidateInput(BaseModel):
    title: str
    url: str
    snippet: str | None = None
    price_in_card: str | None = None

class LabelledCandidate(BaseModel):
    id: str
    source_fixture: str
    candidate: CandidateInput
    expected_is_product: bool
    expected_confidence_min: float = Field(ge=0.0, le=1.0)
    expected_freshness_signal: Literal["live_marketplace", "static_catalog", "blog", "unknown"]
    expected_price_hint: float | None = None
```

**Adapt this pattern** for `SearchRequest`, `Candidate`, `Metadata`, `SearchResponse` (RESEARCH.md §Phase Requirements SEARCH-01 + SEARCH-08):
```python
# src/artiscrapper/models.py
from pydantic import BaseModel, Field

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=15, ge=1, le=30)
    visit_timeout_s: int = Field(default=10, ge=3, le=30)

class Candidate(BaseModel):
    url: str
    title: str | None = None
    snippet: str | None = None
    price: str | None = None
    currency: str | None = None
    has_price: bool = False
    fresh: bool | None = None
    llm_confidence: float = 0.0
    freshness_signal: str = "unknown"
    flags: list[str] = Field(default_factory=list)

class Metadata(BaseModel):
    # SEARCH-08: 8 required fields + block_detected (BROWSER-05) = 9 total
    elapsed_ms: int
    google_fetches: int = 2
    candidates_total: int = 0
    llm_filtered_out: int = 0
    visited: int = 0
    visit_failed: int = 0
    cache_hit: bool = False
    llm_degraded: bool = False
    block_detected: bool = False  # BROWSER-05: set true when _detect_block fires; defaults false

class SearchResponse(BaseModel):
    # PRD §3 response shape: {query, results, metadata}
    query: str  # echo of the request query (PRD §3)
    results: list[Candidate]
    metadata: Metadata
```

---

#### `src/artiscrapper/browser.py` (Cloak singleton + fetch_serp + _detect_block)

**Analog:** `scripts/spike/02_cloak_smoke.py` (lines 41-164) — exact same role and data flow.

**Import pattern** (from `scripts/spike/02_cloak_smoke.py` lines 32-39):
```python
# Phase 1 confirmed: cloakbrowser 0.3.31 exports launch_async at top level
# NOT async_playwright — that was the pre-Phase-1 assumption
from cloakbrowser import launch_async  # RESEARCH.md Pattern 7 + SPIKE.md §Browser
```

**Browser launch + ephemeral context pattern** (`scripts/spike/02_cloak_smoke.py` lines 109-165):
```python
browser = await cloakbrowser.launch_async(
    headless=True,
    args=["--no-sandbox", "--disable-dev-shm-usage"],
)
# Per-request: D8 invariant — NEVER launch_persistent_context
ctx = await browser.new_context(
    locale="es-AR",
    timezone_id="America/Argentina/Buenos_Aires",
    viewport={"width": 1366, "height": 768},
    # NO storage_state, NO user_data_dir
)
try:
    page = await ctx.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
    html = await page.content()
    await page.close()
    return html, block_reason
finally:
    await ctx.close()  # ALWAYS in finally — prevents context leaks
```

**fetch_serp() production signature** (RESEARCH.md Pattern 7, lines 1091-1113):
```python
async def fetch_serp(browser, url: str, rate_limiter) -> tuple[str, str | None]:
    await rate_limiter.acquire()  # blocks until GOOGLE_MIN_INTERVAL_S elapsed
    ctx = await browser.new_context(
        locale="es-AR",
        timezone_id="America/Argentina/Buenos_Aires",
        viewport={"width": 1366, "height": 768},
    )
    try:
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        block_reason = await _detect_block(page)
        html = await page.content()
        await page.close()
        return html, block_reason
    finally:
        await ctx.close()
```

**_detect_block() pattern** (RESEARCH.md Pattern 8, lines 1126-1155):
```python
BLOCK_MARKERS = (
    "detected unusual traffic",
    "captcha",
    "sorry/index",
    "g-recaptcha",
    'id="captcha-form"',
    "before you continue",
    "aria-label=\"antes de continuar",
)

async def _detect_block(page) -> str | None:
    url = str(page.url or "")
    if "/sorry/" in url or "/sorry?" in url:
        return "sorry_redirect"
    content = await page.content()
    content_lower = content.lower()
    if "g-recaptcha" in content_lower or 'id="captcha-form"' in content_lower:
        return "captcha_form"
    if "unusual traffic" in content_lower:
        return "unusual_traffic"
    title_el = await page.title() or ""
    if "unusual traffic" in title_el.lower():
        return "unusual_traffic_title"
    return None
```

**When block detected:** DO NOT write to cache; return HTTP 503 with `metadata.block_detected=true`; log `google.fetch.blocked reason=<reason>` — NO query string in log.

---

#### `src/artiscrapper/rate_limit.py` (GoogleRateLimiter)

**Analog:** NO-ANALOG (no rate limiter in spike scripts)
**Canonical reference:** RESEARCH.md Pattern 1 references `GoogleRateLimiter(min_interval_s=...)` with a `Semaphore(1) + timestamp` pattern.

**Pattern to implement:**
```python
import asyncio, time

class GoogleRateLimiter:
    """Serializes Google fetches: asyncio.Semaphore(1) + timestamp gate."""
    def __init__(self, min_interval_s: float = 60.0):
        self._sem = asyncio.Semaphore(1)
        self._last_fetch: float = 0.0
        self._min_interval = min_interval_s

    async def acquire(self) -> None:
        async with self._sem:
            elapsed = time.monotonic() - self._last_fetch
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_fetch = time.monotonic()
```

---

#### `src/artiscrapper/search.py` (SERP URL builder + parser cascade + canonicalize + dedupe + blocklist + rerank)

**Analog:** `scripts/spike/08_extruct_classifier.py` (parser functions, lines 55-135) — same role (HTML parsing with selectolax) and data flow.

**Analog import pattern** (`scripts/spike/08_extruct_classifier.py` lines 39-44):
```python
try:
    from selectolax.parser import HTMLParser
except ImportError:
    print("ERROR: selectolax not installed", file=sys.stderr)
    sys.exit(1)
```

**build_serp_url() pattern** (RESEARCH.md Pattern 9, lines 1173-1184):
```python
from urllib.parse import urlencode, quote

def build_serp_url(query: str, *, meli: bool = False) -> str:
    """D3: pws=0&safe=off always. NO num/tbm/udm/site:."""
    q = f"{query} mercadolibre" if meli else query
    params = urlencode(
        {"q": q, "hl": "es", "gl": "ar", "pws": "0", "safe": "off"},
        quote_via=quote,
    )
    return f"https://www.google.com/search?{params}"
```

**Parser cascade pattern** (RESEARCH.md §Code Examples, lines 1482-1516):
```python
ORGANIC_SELECTORS = [
    "div.MjjYud div.tF2Cxc",       # 2024-2026 primary (Phase 1 confirmed)
    "div.MjjYud",                  # 2025+ wrapper fallback
    "div.g",                       # legacy
    "div[data-sokoban-container]", # 2025-2026 experimental
    "div[data-snc]",               # mobile variants
]
CAROUSEL_SELECTORS = [
    "div.Ez5pwe",                  # carousel (Phase 1 fixtures confirmed present)
    "g-scrolling-carousel div[role='listitem']",
]

def parse_serp(html: str) -> list[dict]:
    tree = HTMLParser(html)
    candidates = []
    for sel in ORGANIC_SELECTORS:
        nodes = tree.css(sel)
        if nodes:
            results = [_extract_organic(n) for n in nodes]
            results = [r for r in results if r]
            if results:
                candidates.extend(results)
                break
    else:
        log.warning("parse_cascade_exhausted")
        candidates.extend(_extract_by_h3(tree))
    for sel in CAROUSEL_SELECTORS:
        nodes = tree.css(sel)
        if nodes:
            candidates.extend([_extract_carousel(n) for n in nodes if _extract_carousel(n)])
            break
    return candidates
```

**URL canonicalization + dedupe pattern** (RESEARCH.md §Code Examples, lines 1521-1547):
```python
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

STRIP_PARAMS = {"utm_source","utm_medium","utm_campaign","utm_content","utm_term",
                "fbclid","gclid","ved","usg","sa","ei"}

def canonicalize_url(url: str) -> str:
    p = urlparse(url)
    qs = {k: v for k, v in parse_qs(p.query).items() if k not in STRIP_PARAMS}
    return urlunparse((p.scheme, p.netloc.lower().rstrip("/"),
                       p.path.rstrip("/") or "/", p.params,
                       urlencode(qs, doseq=True), ""))

def dedupe(candidates: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for c in candidates:
        key = canonicalize_url(c["url"])
        if key not in seen:
            seen.add(key)
            c["url"] = key
            out.append(c)
    return out
```

**Junk-domain blocklist pattern** (RESEARCH.md §Code Examples, lines 1551-1565):
```python
JUNK_DOMAINS = frozenset({
    "youtube.com", "www.youtube.com",
    "reddit.com", "www.reddit.com",
    "wikipedia.org", "es.wikipedia.org",
    "medium.com", "www.medium.com",
})
JUNK_DOMAIN_SUFFIXES = (".fandom.com", ".gov.ar", ".medium.com")

def is_junk(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    if host in JUNK_DOMAINS:
        return True
    return any(host.endswith(s) for s in JUNK_DOMAIN_SUFFIXES)
```

**Re-rank pattern** (RESEARCH.md §Code Examples, lines 1570-1576):
```python
def rerank(candidates: list[dict], max_results: int = 15) -> list[dict]:
    def sort_key(c: dict):
        has_price = 1 if c.get("price") else 0
        fresh = 1 if c.get("fresh") is True else 0
        confidence = c.get("llm_confidence", 0.0)
        return (has_price, fresh, confidence)
    return sorted(candidates, key=sort_key, reverse=True)[:max_results]
```

---

### PLAN 02-02 — LLM Curator + Visit Pass + Cache

---

#### `src/artiscrapper/llm.py` (LLMVerdict + classify_candidate + SYSTEM_PROMPT + should_keep)

**Analog:** `scripts/spike/05_router_probe.py` (lines 100-220) — same role (httpx POST to OpenAI-compat router) and data flow.

**Router call shape confirmed by spike** (`scripts/spike/05_router_probe.py` lines 138-155):
```python
body = {
    "model": "chat-local",
    "messages": [{"role": "user", "content": '...'}],
    "response_format": {"type": "json_object"},
    "temperature": 0.0,
    "max_tokens": 40,
    "stream": False,
}
async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
    r = await client.post(url, headers=_auth_headers(token), json=body)
# Response path: choices[0].message.content (OpenAI-compat, NOT message.content)
content = resp_data.get("choices", [{}])[0].get("message", {}).get("content", "")
```

**Bearer token pattern** (`scripts/spike/05_router_probe.py` lines 84-88):
```python
def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
```

**LLMVerdict model + fallback()** (RESEARCH.md Pattern 5, lines 796-820):
```python
from pydantic import BaseModel, Field, ValidationError
from typing import Literal

FreshnessSignal = Literal["live_marketplace", "static_catalog", "blog", "unknown"]

class LLMVerdict(BaseModel):
    is_product: bool
    confidence: float = Field(ge=0.0, le=1.0)
    price_hint: float | None = None
    store_hint: str | None = Field(default=None, max_length=80)
    freshness_signal: FreshnessSignal
    reason: str = Field(max_length=140)

    @classmethod
    def fallback(cls, reason: str) -> "LLMVerdict":
        """
        CRITICAL D2 FOOT-GUN: confidence=0.3 is BELOW the <0.4 cut.
        'Permissive' means no exception, NOT that we keep the candidate.
        """
        return cls(
            is_product=True, confidence=0.3, price_hint=None, store_hint=None,
            freshness_signal="unknown", reason=f"llm_fail:{reason}",
        )
```

**classify_candidate() with Semaphore + error handling** (RESEARCH.md Pattern 5, lines 861-925):
```python
async def classify_candidate(
    client: httpx.AsyncClient,
    candidate: dict,
    sem: asyncio.Semaphore,
    router_url: str,
    bearer_token: str,
) -> LLMVerdict:
    async with sem:
        payload = {
            "model": "chat-local",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT + FEW_SHOT_EXAMPLES},
                {"role": "user", "content": USER_TEMPLATE.format(
                    candidate_json=json.dumps(
                        {k: candidate.get(k) for k in ("title", "url", "snippet")},
                        ensure_ascii=False,
                    )
                )},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0, "max_tokens": 128, "stream": False,
        }
        try:
            resp = await client.post(
                f"{router_url}/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {bearer_token}"},
                timeout=5.0,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            return LLMVerdict.model_validate_json(raw)
        except httpx.TimeoutException:
            return LLMVerdict.fallback("timeout")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 503:
                await asyncio.sleep(1.0)
                # single retry (see RESEARCH.md Pattern 5 lines 908-921)
                ...
            return LLMVerdict.fallback(f"http_{e.response.status_code}")
        except (json.JSONDecodeError, ValidationError, KeyError):
            return LLMVerdict.fallback("malformed")
        except Exception:
            return LLMVerdict.fallback("conn_error")

def should_keep(verdict: LLMVerdict) -> bool:
    """D2 FOOT-GUN: 0.3 fallback IS dropped here. This is intentional."""
    if not verdict.is_product:
        return False
    if verdict.confidence < 0.4:
        return False  # D2: 0.3 < 0.4 → DROPPED
    if verdict.freshness_signal == "blog":
        return False
    return True
```

**Spanish SYSTEM_PROMPT + FEW_SHOT_EXAMPLES** (RESEARCH.md Pattern 5, lines 822-857): lift verbatim — the prompt is the canonical source.

**Semaphore orchestration** (LLM_CONCURRENCY=4, empirically confirmed Phase 1):
```python
sem = asyncio.Semaphore(settings.LLM_CONCURRENCY)  # default 4
async with httpx.AsyncClient(http2=True) as client:
    verdicts = await asyncio.gather(*[
        classify_candidate(client, c, sem, settings.LLM_ROUTER_URL, settings.LLM_ROUTER_BEARER_TOKEN)
        for c in candidates
    ])
```

---

#### `src/artiscrapper/visit.py` (visit orchestrator + classify_response + extract_product)

**Analog:** `scripts/spike/07_falabella_403.py` (httpx calls) + `scripts/spike/08_extruct_classifier.py` (extractor functions).

**httpx orchestration with dual semaphores** (RESEARCH.md Pattern 4, lines 651-737):
```python
import asyncio
from collections import defaultdict
from urllib.parse import urlparse
import httpx

GLOBAL_VISIT_CAP = 8
PER_HOST_CAP = 2

async def visit_candidates(candidates: list[dict], visit_timeout_s: int = 10) -> list[dict]:
    global_sem = asyncio.Semaphore(GLOBAL_VISIT_CAP)
    host_sems: dict[str, asyncio.Semaphore] = defaultdict(
        lambda: asyncio.Semaphore(PER_HOST_CAP)
    )

    async def visit_one(candidate: dict) -> dict:
        url = candidate["url"]
        # VISIT-08: never visit *.mercadolibre.*
        if "mercadolibre." in urlparse(url).netloc:
            candidate["flags"] = candidate.get("flags", []) + ["meli_skip"]
            return candidate
        host = urlparse(url).netloc
        async with global_sem, host_sems[host]:
            try:
                async with httpx.AsyncClient(
                    http2=True, headers=DEFAULT_HEADERS, follow_redirects=True,
                    timeout=httpx.Timeout(connect=3.0, read=float(visit_timeout_s),
                                          write=3.0, pool=2.0),
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                ) as client:
                    resp = await client.get(url)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError):
                candidate["visit_failed"] = True
                return candidate
            outcome = classify_response(resp)
            if outcome == "dead":
                candidate["skip_dead"] = True
                return candidate
            if outcome == "failed":
                candidate["visit_failed"] = True
                return candidate
            extracted = extract_product(resp.text)
            if extracted:
                candidate.update(extracted)
            return candidate

    return await asyncio.gather(*[visit_one(c) for c in candidates])
```

**DEFAULT_HEADERS** (RESEARCH.md Pattern 4, lines 662-681 — D11 invariant):
```python
DEFAULT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/146.0.0.0 Safari/537.36"),
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
```

**classify_response() pattern** (RESEARCH.md Pattern 4, lines 741-767):
```python
DEAD_MARKERS = (
    "404", "no encontrad", "not found", "no disponible",
    "producto agotado", "sold out", "producto no existe",
)
SOFT_404_PATHS = {"", "/", "/home", "/index.html", "/buscar", "/search", "/s"}

def classify_response(response: httpx.Response) -> str:
    if response.status_code >= 400:
        return "failed"
    final_path = urlparse(str(response.url)).path.rstrip("/") or "/"
    if final_path in SOFT_404_PATHS or final_path.startswith("/buscar"):
        return "dead"
    ct = response.headers.get("content-type", "")
    if "html" not in ct:
        return "failed"
    if len(response.content) < 5_000:
        return "failed"
    tree = HTMLParser(response.text)
    title = (tree.css_first("title").text() if tree.css_first("title") else "").lower()
    h1 = (tree.css_first("h1").text() if tree.css_first("h1") else "").lower()
    if any(m in title or m in h1 for m in DEAD_MARKERS):
        return "dead"
    return "live"
```

**extract_product() cascade** (RESEARCH.md Pattern 6, lines 947-1062 — D12 HAND-ROLL confirmed):
Full cascade: `extract_jsonld_product()` → `extract_og_product()` → `extract_microdata_product()` → `extract_price_regex()`. Copy Pattern 6 verbatim — it is the exact extractor confirmed by Phase 1's 9/10 `jsonld-sufficient` fixture result.

**AR_PRICE_PATTERN** (RESEARCH.md Pattern 6, lines 952-955 — copy verbatim):
```python
AR_PRICE_PATTERN = re.compile(
    r'(?:ARS|pesos|ar\$)?\s*\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)',
    re.IGNORECASE,
)
```

---

#### `src/artiscrapper/cache.py` (aiosqlite WAL + gzip BLOBs + lazy TTL + prune loop)

**Analog:** NO-ANALOG (no sqlite in spike scripts)
**Canonical reference:** 02-RESEARCH.md Pattern 2 (lines 427-551)

**DDL + PRAGMAS** (RESEARCH.md Pattern 2, lines 429-459 — copy verbatim):
```python
PRAGMAS = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA mmap_size=268435456",
    "PRAGMA cache_size=-32000",
    "PRAGMA wal_autocheckpoint=1000",
    "PRAGMA busy_timeout=5000",
    "PRAGMA foreign_keys=ON",
]
# DDL: CREATE TABLE IF NOT EXISTS query_cache (cache_key TEXT PRIMARY KEY, ...)
# See RESEARCH.md Pattern 2 lines 429-444 for full schema.
```

**Cache key** (RESEARCH.md Pattern 2, lines 463-475):
```python
import hashlib, re, unicodedata

def normalize_query(query: str) -> str:
    q = query.lower().strip()
    q = unicodedata.normalize("NFKD", q)
    q = re.sub(r"\s+", " ", q)
    q = re.sub(r"[^\w\s]", "", q)
    return q.strip()

def make_cache_key(query: str) -> str:
    return hashlib.sha256(normalize_query(query).encode()).hexdigest()
```

**Insert (gzip BLOBs)** (RESEARCH.md Pattern 2, lines 478-508 — copy verbatim).

**Read (lazy TTL — never DELETE in hot path)** (RESEARCH.md Pattern 2, lines 511-523 — copy verbatim).

**Prune loop + nightly WAL checkpoint** (RESEARCH.md Pattern 2, lines 526-551 — copy verbatim).

---

### PLAN 02-03 — Observability + Deploy + Tests

---

#### `src/artiscrapper/logging_setup.py` (structlog + asgi-correlation-id)

**Analog:** NO-ANALOG (no structlog in spike scripts; spikes use plain `print()`)
**Canonical reference:** 02-RESEARCH.md Pattern 3 (lines 557-644)

**configure_logging() pattern** (RESEARCH.md Pattern 3, lines 569-613 — copy verbatim):
```python
import logging, sys
import structlog

def add_correlation_id(_logger, _method, event_dict: dict) -> dict:
    try:
        from asgi_correlation_id import correlation_id  # 5.0 likely path [ASSUMED]
        if cid := correlation_id.get():
            event_dict["correlation_id"] = cid
    except ImportError:
        from asgi_correlation_id.context import correlation_id  # 4.x fallback
        if cid := correlation_id.get():
            event_dict["correlation_id"] = cid
    return event_dict

def configure_logging(json_logs: bool = True, level: str = "INFO") -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        add_correlation_id,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=True)
    )
    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s")
```

**OBS-05 allow-list wrapper** (RESEARCH.md Pattern 3, lines 629-643):
```python
SAFE_CANDIDATE_FIELDS = {"url_hash", "host", "has_price", "freshness_signal", "confidence"}

def log_candidate_safe(log, candidate: dict, verdict) -> None:
    log.info(
        "candidate_classified",
        url_hash=hashlib.sha256(candidate["url"].encode()).hexdigest()[:12],
        host=urlparse(candidate["url"]).netloc,
        is_product=verdict.is_product,
        confidence=round(verdict.confidence, 2),
        freshness_signal=verdict.freshness_signal,
        # NEVER: title, snippet, url, reason
    )
```

**OPEN QUESTION for 02-03 executor:** asgi-correlation-id 5.0.0 import path changed from 4.3.4. First task must run `python -c "from asgi_correlation_id.context import correlation_id"` to confirm, then adjust the try/except fallback if needed (RESEARCH.md §Open Questions, §Pitfall 9).

---

#### `src/artiscrapper/metrics.py` (Inline counters)

**Analog:** NO-ANALOG
**Canonical reference:** RESEARCH.md Pattern 13 (lines 1368-1389) — copy verbatim.

```python
from collections import defaultdict
from dataclasses import dataclass, field

@dataclass
class Metrics:
    llm_fallback_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    visit_failed_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    browser_recycles_total: int = 0
    block_detected_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))

metrics = Metrics()  # process-singleton (safe with --workers 1)
```

---

#### `Dockerfile` (Multi-stage cloakbrowser base)

**Analog:** NO-ANALOG
**Canonical reference:** RESEARCH.md Pattern 12 (lines 1299-1341) — copy verbatim.

**Critical lines** (RESEARCH.md Pattern 12):
```dockerfile
# Phase 1 NEEDS-PIVOT: libnspr4 + libnss3 are NOT bundled in the wheel
FROM cloakhq/cloakbrowser:0.3.31 AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnspr4 libnss3 tini \
 && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["/usr/bin/tini", "--"]
# D6 FOOT-GUN: --loop asyncio --workers 1 ALWAYS. Never uvloop.
CMD ["uvicorn", "src.artiscrapper.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--loop", "asyncio"]
```

---

#### `compose.yml` (Dev local sqlite bind-mount)

**Analog:** NO-ANALOG
**Canonical reference:** RESEARCH.md Pattern 12 (lines 1342-1361) — copy verbatim.

```yaml
services:
  artiscrapper:
    build: .
    ports: ["8000:8000"]
    volumes:
      - ./data/cache.db:/app/cache.db
    environment:
      - CACHE_DB_PATH=/app/cache.db
      - LLM_ROUTER_URL=http://host.docker.internal:3210
      - LLM_ROUTER_BEARER_TOKEN=${LLM_ROUTER_BEARER_TOKEN}
      - GOOGLE_MIN_INTERVAL_S=60
      - BROWSER_RECYCLE_AFTER=200
      - LLM_CONCURRENCY=4
      - LOG_JSON=true
      - LOG_LEVEL=INFO
    init: true
```

---

#### `pyproject.toml` (Production — supersedes pyproject.toml.spike)

**Analog:** `pyproject.toml.spike` (partial — dep list only; structure differs for production).

**Spike dep list pattern** (`pyproject.toml.spike`):
```toml
[project]
name = "artiscrapper-spike"
version = "0.0.0"
requires-python = ">=3.12"
dependencies = [
    "cloakbrowser==0.3.31",
    "httpx[http2]==0.28.1",
    "httpx-sse>=0.4.0",
    "selectolax==0.4.10",
    "pydantic>=2.0",
]
```

**Production additions** (RESEARCH.md §Standard Stack, lines 166-174):
```bash
# Add to existing spike deps:
fastapi==0.136.3 uvicorn==0.48.0 aiosqlite==0.22.1
structlog==25.5.0 asgi-correlation-id==5.0.0 orjson==3.11.9
tldextract==5.3.1 pydantic-settings>=2.0
# dev group:
pytest>=9.0 pytest-asyncio==1.4.0 respx==0.23.1 ruff>=0.15 mypy>=2.0 pytest-cov
```

**pytest config** (RESEARCH.md §Validation, lines 1604-1605):
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = ["e2e: live network tests (skipped by default)"]
```

---

#### `tests/conftest.py` (Shared test fixtures)

**Analog:** NO-ANALOG (no test infra in Phase 1)
**Canonical reference:** RESEARCH.md Pattern 1 test override block (lines 404-420)

```python
# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock
from artiscrapper.main import app

@pytest.fixture
def mock_app_state(tmp_path):
    app.state.browser = MagicMock()
    app.state.browser.is_connected.return_value = True
    app.state.cache = AsyncMock()
    app.state.browser_uses = 0
    app.state.rate_limit = MagicMock()
    app.state.rate_limit.acquire = AsyncMock()
    yield
```

Also needs a `tmp_db` fixture using `aiosqlite` in-memory or `tmp_path` (use `tmp_path` for filesystem-based db to support WAL mode, which requires a real file, not `:memory:`).

---

#### `tests/test_parser.py` (Unit tests against serp fixtures)

**Analog:** NO-ANALOG for test structure; serp fixtures at `tests/fixtures/serp/*.html` are the data source (10 files from Phase 1).

**Test map from RESEARCH.md** (lines 1612-1616):
- `test_cascade_exhausted_alert`: monkeypatch all selectors to return empty; assert `parse_cascade_exhausted` logged.
- `test_canonicalize`: assert utm_*/gclid/ved stripped; deduplication works.
- `test_blocklist`: assert youtube.com/fandom/wikipedia/reddit all pass `is_junk()`.

---

#### `tests/test_llm.py` (Integration tests with respx mock)

**Analog:** `scripts/spike/05_router_probe.py` — provides the exact request/response shape to mock.

**respx mock pattern** (from RESEARCH.md §Validation, line 1619):
```python
# tests/test_llm.py
import respx, httpx, json
from artiscrapper.llm import classify_candidate, LLMVerdict

@respx.mock
async def test_router_call_shape():
    verdict_json = json.dumps({
        "is_product": True, "confidence": 0.95,
        "price_hint": 8500.0, "store_hint": "Tiendanube",
        "freshness_signal": "static_catalog", "reason": "JSON-LD product"
    })
    respx.post("http://127.0.0.1:3210/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": verdict_json}, "finish_reason": "stop"}]
        })
    )
    # assert classify_candidate returns a valid LLMVerdict
```

**Key invariant to test** (RESEARCH.md §Pitfall 5): the response field path MUST be `choices[0].message.content`, not `message.content`.

---

#### `tests/test_visit.py` (classify_response + extractor unit tests)

**Analog:** `scripts/spike/08_extruct_classifier.py` — provides the exact extractor functions to test against catalog fixtures.

**Catalog fixtures available** (from Phase 1): `tests/fixtures/catalog/{argautopartes,autodo,casasusy,dphidraulica,falabella,lspalermo,martinmorris,mayoristafrog,mipol,reps}_com_ar/product-01.html` (10 files).

**Key tests from RESEARCH.md** (lines 1621-1625):
- `test_extractor_catalog_fixtures`: run `extract_jsonld_product()` against all 9 `jsonld-sufficient` fixtures from Phase 1; assert each returns a dict with `price` set.
- `test_meli_guard`: assert `visit_one({"url": "https://www.mercadolibre.com.ar/..."})` returns candidate with `"meli_skip"` in flags without making any HTTP call.

---

#### `tests/test_footguns.py` (D2 + D6 + D8 invariant assertions)

**Analog:** NO-ANALOG
**Canonical reference:** RESEARCH.md Pattern 10 (lines 1206-1224)

```python
# tests/test_footguns.py
import subprocess, sys
from artiscrapper.llm import LLMVerdict, should_keep

def test_no_uvloop_installed():
    """D6: uvloop must not be importable in runtime env."""
    result = subprocess.run([sys.executable, "-c", "import uvloop"], capture_output=True)
    assert result.returncode != 0, "uvloop is installed — D6 foot-gun!"

def test_uvloop_absent_from_lock():
    """D6: uvloop must not appear in pyproject.toml or uv.lock."""
    result = subprocess.run(
        ["grep", "-rE", "uvloop", "pyproject.toml", "uv.lock"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, f"uvloop found: {result.stdout}"

def test_no_persistent_context_in_codebase():
    """D8: launch_persistent_context must not appear in src/."""
    result = subprocess.run(
        ["grep", "-rn", "launch_persistent_context", "src/"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, f"D8 foot-gun: {result.stdout}"

def test_d2_fallback_is_dropped():
    """D2: timeout fallback confidence=0.3 is BELOW <0.4 cut → dropped."""
    v = LLMVerdict.fallback("timeout")
    assert v.confidence == 0.3
    assert not should_keep(v), "D2 foot-gun: fallback verdict must be dropped!"
```

---

#### `tests/test_cache.py` + `tests/test_health.py` + `tests/test_e2e.py`

**Analogs:** NO-ANALOG
**Canonical references:**
- `test_cache.py`: RESEARCH.md Pattern 2 (DDL, gzip roundtrip, lazy TTL)
- `test_health.py`: RESEARCH.md Pattern 11 (/health + /health/deep shapes)
- `test_e2e.py`: RESEARCH.md §Validation lines 1636-1638 (mark `@pytest.mark.e2e`, skip by default)

---

#### `.github/workflows/ci.yml`

**Analog:** NO-ANALOG
**Canonical reference:** RESEARCH.md Pattern 10 (lines 1193-1200)

**uvloop absence assertion** (RESEARCH.md Pattern 10, lines 1193-1196):
```bash
grep -rE 'uvloop' pyproject.toml uv.lock && echo "FAIL: uvloop found — D6 foot-gun!" && exit 1 || echo "OK: uvloop absent"
grep -q 'loop asyncio' Dockerfile && grep -q 'workers 1' Dockerfile || { echo "FAIL: Dockerfile CMD missing flags"; exit 1; }
```

---

## Shared Patterns

### Browser Launch (D8 invariant)
**Source:** `scripts/spike/02_cloak_smoke.py` (lines 109-165) + RESEARCH.md Pattern 7
**Apply to:** `src/artiscrapper/browser.py`, `src/artiscrapper/main.py` (_recycle_browser_loop heartbeat)
```python
from cloakbrowser import launch_async  # NOT async_playwright
# NEVER: browser.launch_persistent_context(...)
# ALWAYS: await browser.new_context(...) per request
```

### asyncio-only (D6 invariant)
**Source:** `scripts/spike/02_cloak_smoke.py` (line 262) + `scripts/spike/05_router_probe.py` (line 550)
**Apply to:** Every `.py` file under `src/` + Dockerfile CMD
```python
# Every async entry point:
asyncio.run(main())   # NEVER uvloop.install() or uvloop.EventLoopPolicy()
# Dockerfile CMD:
["uvicorn", "...", "--workers", "1", "--loop", "asyncio"]
```

### OBS-05 Allow-list (never log scraped content)
**Source:** RESEARCH.md Pattern 3 (lines 629-643)
**Apply to:** `src/artiscrapper/llm.py`, `src/artiscrapper/visit.py`, `src/artiscrapper/search.py`
```python
# FORBIDDEN in any log call: title=, snippet=, url=, reason=, raw_html=
# ALLOWED: url_hash=, host=, has_price=, confidence=, freshness_signal=
```

### D11 — Sec-Fetch-Site: cross-site + Referer
**Source:** RESEARCH.md Pattern 4 `DEFAULT_HEADERS` (lines 662-681)
**Apply to:** `src/artiscrapper/visit.py` (visit pass only — NOT Cloak/Google fetches)
```python
"Sec-Fetch-Site": "cross-site",
"Referer": "https://www.google.com/",
```

### VISIT-08 — MELI host guard
**Source:** RESEARCH.md Pattern 4 (lines 697-701)
**Apply to:** `src/artiscrapper/visit.py` — MUST be the FIRST check in `visit_one()`
```python
if "mercadolibre." in urlparse(url).netloc:
    candidate["flags"] = candidate.get("flags", []) + ["meli_skip"]
    return candidate
```

### D2 — LLM confidence cut
**Source:** RESEARCH.md Pattern 5 `should_keep()` (lines 928-936)
**Apply to:** `src/artiscrapper/llm.py` — the `should_keep()` function is the ONLY enforcement point
```python
if verdict.confidence < 0.4:
    return False  # 0.3 fallback IS dropped here — intentional
```

### Structlog per-request bindings
**Source:** RESEARCH.md Pattern 3 (lines 617-624)
**Apply to:** `src/artiscrapper/main.py` /search handler (at top of handler)
```python
structlog.contextvars.clear_contextvars()
structlog.contextvars.bind_contextvars(query_hash=cache_key[:12], stage="search")
```

---

## No Analog Found (Summary)

Files with no close match — planner uses 02-RESEARCH.md Pattern N as canonical reference:

| File | Role | Reason | RESEARCH.md Reference |
|------|------|---------|-----------------------|
| `src/artiscrapper/main.py` | FastAPI lifespan | No HTTP server in Phase 1 | Pattern 1 + Pattern 11 |
| `src/artiscrapper/config.py` | pydantic-settings | No settings module in spike | §Arch Responsibility Map |
| `src/artiscrapper/rate_limit.py` | GoogleRateLimiter | No rate limiter in spike | Pattern 1 (GoogleRateLimiter instantiation) |
| `src/artiscrapper/cache.py` | aiosqlite cache | No sqlite in spike | Pattern 2 (copy verbatim) |
| `src/artiscrapper/logging_setup.py` | structlog wiring | Spikes use plain print() | Pattern 3 (copy verbatim) |
| `src/artiscrapper/metrics.py` | Inline counters | No metrics in spike | Pattern 13 (copy verbatim) |
| `Dockerfile` | Multi-stage | No container build in spike | Pattern 12 (copy verbatim) |
| `compose.yml` | Dev compose | No compose in spike | Pattern 12 (copy verbatim) |
| `tests/conftest.py` | Test fixtures | No test infra in Phase 1 | Pattern 1 test override |
| `tests/test_cache.py` | Cache tests | No sqlite in spike | Pattern 2 |
| `tests/test_health.py` | Health tests | No HTTP server in Phase 1 | Pattern 11 |
| `tests/test_footguns.py` | Invariant tests | No test infra in Phase 1 | Pattern 10 (copy verbatim) |
| `tests/test_e2e.py` | Live e2e test | No live HTTP test in Phase 1 | §Validation lines 1636-1638 |
| `.github/workflows/ci.yml` | CI pipeline | No CI in Phase 1 | Pattern 10 (uvloop assertion) |

---

## Metadata

**Analog search scope:** `scripts/spike/` (17 spike scripts) — confirmed no `src/` production code exists.
**Files scanned:** 4 spike scripts read in full (02, 05, 08_extruct_classifier, labels.py); 01-PATTERNS.md read; 02-RESEARCH.md read in full (1771 lines).
**Pattern extraction date:** 2026-06-02
**Primary reference document:** `/home/luis/proyectos/artiscrapper/.planning/phases/02-mvp/02-RESEARCH.md` (single source of truth for all "what to lift verbatim")
**State-of-the-art table:** See 02-RESEARCH.md lines 1581-1592 for "Old State vs Current State" — executor MUST read this table before writing any browser.py or llm.py code (3 pivots invalidate all pre-Phase-1 research briefs).
