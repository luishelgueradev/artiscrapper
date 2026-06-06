#!/usr/bin/env python3
"""
02_cloak_smoke.py — Cold-boot smoke + pws=0 SERP capture + cookie isolation.

Implements two probes combined:
  - Pattern 1: Cold-container browser smoke (01-RESEARCH.md lines 267-322)
  - Pattern 3: Ephemeral context cookie isolation (01-RESEARCH.md lines 368-400)

References:
  01-RESEARCH.md §Pattern 1 (lines 267-322)
  01-RESEARCH.md §Pattern 3 (lines 368-400)
  01-RESEARCH.md §Pitfall 1 (lines 741-745) — import path discipline
  01-RESEARCH.md §Pitfall 2 (lines 747-751) — pws=0 interstitial risk
  01-RESEARCH.md §Anti-Patterns (line 712) — ≤1/min SERP throttle

Exit codes:
  0 — smoke captured ≥5 fixtures AND cookie isolation PASSED
  1 — smoke failed or cookie isolation FAILED
  2 — missing .env.spike (N/A for this script — no LLM calls)
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Pitfall 1: Cloak import path discovery ──────────────────────────────────
# cloakbrowser 0.3.31 does NOT export async_playwright directly.
# Its own API is cloakbrowser.launch_async() / launch_context_async().
# After import, playwright.async_api is available via the bundled playwright.
try:
    from cloakbrowser import launch_async  # noqa: F401
    CLOAK_IMPORT = "cloakbrowser.launch_async"
    print(f"Cloak Python import path: {CLOAK_IMPORT}")
except ImportError:
    print("ERROR: cloakbrowser not installed — run: uv pip install cloakbrowser==0.3.31", file=sys.stderr)
    sys.exit(1)

import cloakbrowser

# ── Constants (verbatim from 01-RESEARCH.md lines 281-295) ──────────────────
GOOGLE = "https://www.google.com/search?q={q}&hl=es&gl=ar&pws=0&safe=off"

QUERIES = [
    "pelota playera quico", "filtro aceite ford focus", "amortiguador trasero peugeot 208",
    "buja ngk bosch", "correa distribucion fiat cronos", "disco freno renault sandero",
    "rotula direccion vw gol", "kit embrague chevrolet onix", "termostato corsa classic",
    "balatas brembo toyota hilux",
]

INTERSTITIAL_MARKERS = [
    'id="L2AGLb"',                          # "I agree" button on consent screen (EU + ES variant)
    'href="https://policies.google.com',    # consent screen meta
    'aria-label="Antes de continuar',       # "Before you continue" ES
    '/sorry/index',                         # block challenge
    'g-recaptcha',                          # captcha
]

# ── D8 invariant guard ─────────────────────────────────────────────────────
# Verify no actual calls to the forbidden function exist in non-guard, non-comment lines.
# The token is split across two string literals so the guard itself cannot self-match.
_D8_FORBIDDEN = "launch_persistent" + "_context("
_D8_LINES = Path(__file__).read_text(encoding="utf-8").splitlines()
_D8_VIOLATIONS = [
    (i + 1, line)
    for i, line in enumerate(_D8_LINES)
    if _D8_FORBIDDEN in line and not line.strip().startswith("#") and "_D8_" not in line
]
if _D8_VIOLATIONS:
    for lineno, line in _D8_VIOLATIONS:
        print(f"FATAL D8: line {lineno}: {line.strip()}", file=sys.stderr)
    sys.exit(1)

# ── D6 invariant reminder — asyncio only, no uvloop ─────────────────────────
# NEVER: uvloop.install() or asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


async def smoke(out_dir: Path) -> list[dict]:
    """
    Pattern 1: Cold-container browser smoke + SERP capture.
    Opens one ephemeral context per query, captures raw HTML.
    Throttle: ≥60s between fetches (01-RESEARCH.md line 712).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "MANIFEST.md"

    # Initialize MANIFEST.md if not present
    if not manifest_path.exists():
        manifest_path.write_text(
            "# SERP Fixture Manifest\n\n"
            "| filename | query | bytes | marker_hits | captured_at |\n"
            "|----------|-------|-------|-------------|-------------|\n",
            encoding="utf-8",
        )

    # Count existing fixtures to avoid re-capturing
    existing = list(out_dir.glob("*.html"))
    existing_count = len(existing)
    print(f"[02_cloak_smoke] Existing fixtures: {existing_count}")

    if existing_count >= 10:
        print("[02_cloak_smoke] Already have 10 fixtures — skip capture")
        return []

    results = []
    # Use cloakbrowser.launch_async + browser.new_context (D8 invariant)
    browser = await cloakbrowser.launch_async(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    print(f"[02_cloak_smoke] browser.is_connected(): {browser.is_connected()}")

    queries_to_run = QUERIES[:max(5, 10 - existing_count)]
    print(f"[02_cloak_smoke] Capturing {len(queries_to_run)} queries (need ≥5 total)")

    for i, q in enumerate(queries_to_run, start=existing_count + 1):
        ctx = await browser.new_context(
            locale="es-AR",
            timezone_id="America/Argentina/Buenos_Aires",
            viewport={"width": 1366, "height": 768},
        )
        print(f"[02_cloak_smoke] ctx id: {id(ctx)} — context {i}")
        page = await ctx.new_page()
        url = GOOGLE.format(q=q.replace(" ", "+"))

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            html = await page.content()
            hits = [m for m in INTERSTITIAL_MARKERS if m in html]
            byte_count = len(html.encode("utf-8"))
            slug = q.replace(" ", "_").replace("/", "_")
            out_path = out_dir / f"{i:02d}-{slug}.html"
            out_path.write_text(html, encoding="utf-8")

            captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            marker_str = ", ".join(hits) if hits else "none"

            # Append to MANIFEST.md
            manifest_line = f"| {out_path.name} | \"{q}\" | {byte_count} | {marker_str} | {captured_at} |\n"
            with manifest_path.open("a", encoding="utf-8") as mf:
                mf.write(manifest_line)

            # Pitfall 2 warning: fixture < 35KB is likely consent interstitial
            size_kb = byte_count / 1024
            if size_kb < 35:
                print(f"WARNING: fixture {out_path.name} only {size_kb:.1f}KB — likely consent stub")
            elif size_kb < 100:
                print(f"WARNING: fixture {out_path.name} only {size_kb:.1f}KB — may be partial page")

            print(f"[{i:02d}] q='{q}' interstitial_hits={hits} bytes={byte_count} ({size_kb:.0f}KB)")
            results.append({"file": str(out_path), "query": q, "bytes": byte_count, "hits": hits})
        except Exception as e:
            print(f"[{i:02d}] ERROR fetching q='{q}': {e}")

        await page.close()
        await ctx.close()

        if i < existing_count + len(queries_to_run):
            print("[02_cloak_smoke] Throttle: sleeping 60s between queries...")
            await asyncio.sleep(60)

    await browser.close()
    return results


async def cookie_isolation_test() -> bool:
    """
    Pattern 3: Ephemeral context cookie isolation.
    Sets a marker cookie in ctx1, then verifies it does NOT appear in ctx2.
    (01-RESEARCH.md lines 373-398 verbatim)
    """
    print("[02_cloak_smoke] Running cookie isolation test...")

    browser = await cloakbrowser.launch_async(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    print(f"[02_cloak_smoke] Cookie test — ctx1 id: using browser {id(browser)}")

    # Set marker cookie in ctx1
    ctx1 = await browser.new_context(locale="es-AR")
    page1 = await ctx1.new_page()
    await page1.goto("https://www.google.com/", wait_until="domcontentloaded", timeout=20_000)
    await ctx1.add_cookies([
        {"name": "artispike_marker", "value": "42", "domain": ".google.com", "path": "/"}
    ])
    cookies1 = await ctx1.cookies("https://www.google.com/")
    cookie_names_1 = [c["name"] for c in cookies1]
    print(f"ctx1 cookies after set: {cookie_names_1}")
    await ctx1.close()

    # New ephemeral context — must NOT see marker
    ctx2 = await browser.new_context(locale="es-AR")
    page2 = await ctx2.new_page()

    captured_headers: dict[str, dict] = {}

    async def on_request(req):
        captured_headers[req.url] = req.headers

    page2.on("request", on_request)

    await page2.goto("https://www.google.com/", wait_until="domcontentloaded", timeout=20_000)
    cookies2 = await ctx2.cookies("https://www.google.com/")
    cookie_names_2 = [c["name"] for c in cookies2]
    print(f"ctx2 cookies after nav: {cookie_names_2}")

    g_url = next((u for u in captured_headers if "google.com" in u), None)
    cookie_header = (captured_headers.get(g_url, {}) or {}).get("cookie", "(none)")
    print(f"ctx2 request Cookie header: {cookie_header}")

    isolation_pass = "artispike_marker" not in (cookie_header or "")
    if isolation_pass:
        print("cookie isolation: PASS")
    else:
        print("cookie isolation: FAIL — artispike_marker leaked into ctx2!")

    await ctx2.close()
    await browser.close()
    return isolation_pass


async def main(out_dir_str: str) -> None:
    out_dir = Path(out_dir_str)
    print(f"[02_cloak_smoke] Output dir: {out_dir.resolve()}")

    # Step 1: Smoke + capture
    await smoke(out_dir)

    # Step 2: Count fixtures
    fixtures = list(out_dir.glob("*.html"))
    fixture_count = len(fixtures)
    print(f"[02_cloak_smoke] Total fixtures on disk: {fixture_count}")

    # Pitfall 2: check sizes
    for fixture in fixtures:
        size_kb = fixture.stat().st_size / 1024
        if size_kb < 35:
            print(f"WARNING: fixture {fixture.name} only {size_kb:.1f}KB — likely consent stub")

    # Step 3: Cookie isolation
    isolation_ok = await cookie_isolation_test()

    # Final verdict
    smoke_ok = fixture_count >= 5
    if smoke_ok and isolation_ok:
        print(f"[02_cloak_smoke] PASS: {fixture_count} fixtures captured, cookie isolation OK")
        sys.exit(0)
    else:
        failures = []
        if not smoke_ok:
            failures.append(f"only {fixture_count} fixtures (need ≥5)")
        if not isolation_ok:
            failures.append("cookie isolation FAIL")
        print(f"[02_cloak_smoke] FAIL: {'; '.join(failures)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/serp"))
