"""
Cloak browser operations: create_browser, fetch_serp, _detect_block.
Pattern 7 (launch_async + new_context chain) + Pattern 8 (_detect_block markers)
from 02-RESEARCH.md.
Phase 1 confirmed: import path is `from cloakbrowser import launch_async`.
D8: ephemeral new_context() per request ONLY — no persistent contexts.
BROWSER-01: singleton. BROWSER-02: ephemeral context. BROWSER-04: rate_limiter.acquire().
BROWSER-05: _detect_block.
"""

import structlog
from cloakbrowser import launch_async  # Phase 1 confirmed import path

log = structlog.get_logger()


# D8 invariant: only ephemeral new_context() calls are permitted (no persistent contexts).
# Confirmed by test_footguns.py::test_no_persistent_context_in_codebase.

BLOCK_MARKERS = (
    "detected unusual traffic",
    "captcha",
    "sorry/index",  # URL path marker
    "g-recaptcha",  # DOM marker
    'id="captcha-form"',  # DOM marker
    "before you continue",  # consent interstitial (pws=0 was clean, but defensive)
    'aria-label="antes de continuar',  # ES variant
)


async def create_browser(headless: bool = True):
    """
    Boot the singleton Cloak Browser.
    Called once in lifespan — returns the Browser singleton.
    Pattern 7 from 02-RESEARCH.md.
    Phase 1: await launch_async(headless=True) works in cloakbrowser 0.3.31.
    """
    browser = await launch_async(headless=headless)
    return browser


async def _detect_block(page) -> str | None:
    """
    Returns a block_reason string or None.
    Pattern 8 from 02-RESEARCH.md (lines 1136-1155).
    Phase 1: all 10 fixtures clean under D3 URL params — still implement defensively.
    NEVER log the content (OBS-05).
    """
    url = str(page.url or "")
    if "/sorry/" in url or "/sorry?" in url:
        return "sorry_redirect"
    # Content sniff: cheap string checks, NEVER log the content
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


async def fetch_serp(browser, url: str, rate_limiter) -> tuple[str, str | None]:
    """
    Fetch a Google SERP URL with an ephemeral context.
    Returns (html, block_reason | None).
    D8: ephemeral new_context() per request — no persistent context.
    Pattern 7 from 02-RESEARCH.md (lines 1091-1113).
    """
    await rate_limiter.acquire()  # blocks until GOOGLE_MIN_INTERVAL_S elapsed
    ctx = await browser.new_context(
        locale="es-AR",
        timezone_id="America/Argentina/Buenos_Aires",
        viewport={"width": 1366, "height": 768},
        # NO storage_state, NO user_data_dir — D8 invariant
    )
    try:
        page = await ctx.new_page()
        # PARITY: wait_until="load" recupera el Shopping panel (div.pla-unit)
        # y JSON-inline mappings que "domcontentloaded" corta antes de renderizar.
        # Sin penalty p50 según Exp 2 del reporte (3.1s avg vs 5.6s con dom).
        # Timeout bajado a 15s para fail-fast — siempre que Google sirva en tiempo
        # razonable la SERP completa, "load" termina antes; queries lentas fallan
        # rápido en vez de esperar 20s sin progreso.
        # Ver .planning/PARSER-VISUAL-PARITY-2026-06-05.md §2.
        await page.goto(url, wait_until="load", timeout=15_000)
        block_reason = await _detect_block(page)
        html = await page.content()
        await page.close()
        return html, block_reason
    finally:
        await ctx.close()  # ALWAYS close in finally — prevents context leaks
