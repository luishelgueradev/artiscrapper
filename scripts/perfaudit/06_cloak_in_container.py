"""Cloak baseline inside container."""
import asyncio
import sys
import time
sys.path.insert(0, "/app")
from cloakbrowser import launch_async


async def fetch_via_cloak(browser, url):
    ctx = await browser.new_context(
        locale="es-AR",
        viewport={"width": 1366, "height": 768},
    )
    try:
        page = await ctx.new_page()
        start = time.perf_counter()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = await page.content()
            return time.perf_counter() - start, len(html), None
        except Exception as e:
            return time.perf_counter() - start, 0, f"{type(e).__name__}: {e}"
        finally:
            await page.close()
    finally:
        await ctx.close()


async def main():
    print("Launching Cloak...")
    s = time.perf_counter()
    browser = await launch_async()
    print(f"Launch: {time.perf_counter()-s:.2f}s\n")

    urls = [
        ("data:text/html,<html><body>OK</body></html>", "data-url"),
        ("https://example.com", "example.com"),
        ("https://www.google.com/search?q=test&pws=0&safe=off", "google REAL"),
    ]
    print("=== Cold sequential ===")
    for url, label in urls:
        e, l, err = await fetch_via_cloak(browser, url)
        print(f"  [{e*1000:>6.0f}ms] {label}  html={l}b  err={err}")

    print("\n=== Warm (3x example.com) ===")
    for _ in range(3):
        e, l, err = await fetch_via_cloak(browser, "https://example.com")
        print(f"  [{e*1000:>6.0f}ms]  err={err}")

    print("\n=== Parallel 2x example.com ===")
    s = time.perf_counter()
    r = await asyncio.gather(
        fetch_via_cloak(browser, "https://example.com"),
        fetch_via_cloak(browser, "https://example.com?q=2"),
    )
    print(f"  Wall-clock parallel: {(time.perf_counter()-s)*1000:.0f}ms")
    for i, (e, l, err) in enumerate(r):
        print(f"    fetch {i}: {e*1000:.0f}ms")

    print("\n=== Parallel 2x google (real test) ===")
    s = time.perf_counter()
    r = await asyncio.gather(
        fetch_via_cloak(browser, "https://www.google.com/search?q=filtro+aceite+ford&pws=0&safe=off"),
        fetch_via_cloak(browser, "https://www.google.com/search?q=filtro+aceite+ford+mercadolibre&pws=0&safe=off"),
    )
    print(f"  Wall-clock parallel google: {(time.perf_counter()-s)*1000:.0f}ms")
    for i, (e, l, err) in enumerate(r):
        print(f"    fetch {i}: {e*1000:.0f}ms html={l}b err={err}")

    await browser.close()


asyncio.run(main())
