"""
Mide el costo real de UN fetch via Cloak.

Hipótesis: la mayor parte del tiempo es Chromium startup + navigation, no
networking. Medir contra una URL que NO bloquea (data: o un endpoint simple)
para aislar el costo de Cloak/Chromium.

Después comparar con un fetch real a Google para ver cuánto pesa el block-detection.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cloakbrowser import launch_async  # noqa: E402


async def fetch_via_cloak(browser, url: str) -> tuple[float, int, str | None]:
    """Returns (elapsed_s, html_len, error)."""
    ctx = await browser.new_context(
        locale="es-AR",
        timezone_id="America/Argentina/Buenos_Aires",
        viewport={"width": 1366, "height": 768},
    )
    try:
        page = await ctx.new_page()
        start = time.perf_counter()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = await page.content()
            elapsed = time.perf_counter() - start
            return elapsed, len(html), None
        except Exception as e:
            elapsed = time.perf_counter() - start
            return elapsed, 0, f"{type(e).__name__}: {e}"
        finally:
            await page.close()
    finally:
        await ctx.close()


async def main():
    print("Launching Cloak singleton...")
    start = time.perf_counter()
    browser = await launch_async()
    launch_s = time.perf_counter() - start
    print(f"Cloak launch: {launch_s:.2f}s\n")

    urls = [
        ("data:text/html,<html><body>OK</body></html>", "data-url (baseline puro)"),
        ("https://example.com", "example.com (sin JS)"),
        ("https://httpbin.org/html", "httpbin.org/html (sin JS, AR ISP-friendly)"),
        ("https://www.google.com/search?q=test&pws=0&safe=off", "Google REAL (puede dar sorry)"),
    ]

    print("=== Cold fetches (cada uno crea nuevo context) ===")
    for url, label in urls:
        elapsed, html_len, err = await fetch_via_cloak(browser, url)
        print(f"  [{elapsed*1000:>6.0f}ms] {label}  html={html_len}b  err={err}")

    print("\n=== Warm: 3 fetches consecutivos a la misma URL (Cloak reusing browser) ===")
    for _ in range(3):
        elapsed, html_len, err = await fetch_via_cloak(browser, "https://example.com")
        print(f"  [{elapsed*1000:>6.0f}ms]  err={err}")

    print("\n=== Parallel: 2 fetches CONCURRENTES (lo que /search hace) ===")
    start = time.perf_counter()
    results = await asyncio.gather(
        fetch_via_cloak(browser, "https://example.com"),
        fetch_via_cloak(browser, "https://example.com?q=2"),
    )
    par_elapsed = time.perf_counter() - start
    print(f"  Wall-clock parallel: {par_elapsed*1000:.0f}ms")
    for i, (e, l, err) in enumerate(results):
        print(f"    [{e*1000:>6.0f}ms] fetch {i}  html={l}b  err={err}")

    await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
