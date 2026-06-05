"""One-off capture for Phase 0.2.3 page-2 fixtures.

Run inside the container (preferred — Cloak's chromium pin is pre-installed):

    docker compose exec artiscrapper python scripts/capture_page2_fixtures.py

Or directly against the worktree venv (requires playwright browsers already
installed):

    .venv/bin/python scripts/capture_page2_fixtures.py

Captures 2 page-2 SERP HTMLs (organic-heavy + pla-heavy) per CONTEXT D-13:
  - page2_termotanque.html — "termotanque rheem 80 litros electrico"
  - page2_zapatillas.html — "zapatillas nike air max hombre 42"

Per Phase 0.2.1 convention, strips base64 images + inline scripts to keep
the fixture small enough for git (~1 MB typical).

Failure modes (autonomous-overnight policy — Luis):
  - CAPTCHA / soft-block / network error → caller falls back to synthesis.
  - Browser binary missing → out of scope; caller fails fast and synthesizes.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import quote

from cloakbrowser import launch_async

QUERIES = [
    ("page2_termotanque", "termotanque rheem 80 litros electrico"),
    ("page2_zapatillas", "zapatillas nike air max hombre 42"),
]
URL_FMT = (
    "https://www.google.com/search?q={q}&hl=es&gl=ar&pws=0&safe=off&start=10"
)


CAPTCHA_MARKERS = ("g-recaptcha", "sorry/index", "/sorry/")


async def main() -> int:
    browser = await launch_async(headless=True)
    failures: list[str] = []
    try:
        for slug, query in QUERIES:
            ctx = await browser.new_context(
                locale="es-AR",
                timezone_id="America/Argentina/Buenos_Aires",
                viewport={"width": 1366, "height": 768},
            )
            try:
                page = await ctx.new_page()
                url = URL_FMT.format(q=quote(query))
                await page.goto(url, wait_until="load", timeout=15_000)
                html = await page.content()

                # Strip base64 images + inline scripts (Phase 0.2.1 convention).
                cleaned = re.sub(
                    r'data:image/[^"\']*',
                    'data:image/png;base64,PLACEHOLDER',
                    html,
                )
                cleaned = re.sub(
                    r'<script[^>]*>.*?</script>',
                    '<script></script>',
                    cleaned,
                    flags=re.DOTALL,
                )

                # CAPTCHA / soft-block sniff — bail before writing a useless fixture.
                if any(m in cleaned for m in CAPTCHA_MARKERS):
                    failures.append(f"{slug}: CAPTCHA / soft-block detected")
                    print(f"[FAIL] {slug}: blocked", file=sys.stderr)
                    continue

                out = Path(f"tests/fixtures/serp/{slug}.html")
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(cleaned)
                print(f"saved {out} ({len(cleaned)} bytes)")
            finally:
                await ctx.close()
    finally:
        await browser.close()

    if failures:
        for f in failures:
            print(f"FAILED: {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
