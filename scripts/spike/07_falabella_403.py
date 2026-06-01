#!/usr/bin/env python3
"""
07_falabella_403.py — httpx 403-rate probe for Falabella + Frog + Romero (D11 gate).

Fires N=10 sequential httpx GETs at 10 PDP URLs per host, recording the status code
distribution. Outputs per-host artifact file and a verdict line:
  D11_VERDICT_{host}: realistic-headers-sufficient | realistic-headers-insufficient | borderline

References:
  01-RESEARCH.md §Pattern 6 (lines 619-670) — DEFAULT_HEADERS, async loop
  01-RESEARCH.md §Pitfall 5 (lines 765-769) — N≥10 over ≥60s, ratio not binary

Usage:
  python scripts/spike/07_falabella_403.py --host=falabella
  python scripts/spike/07_falabella_403.py --host=frog
  python scripts/spike/07_falabella_403.py --host=romero

Exit codes:
  0 — probe completed (verdict written; outcome may be any status mix)
  1 — missing URL list for this host
  2 — invalid --host value

D11 invariant: DEFAULT_HEADERS must include Sec-Fetch-Site and Referer verbatim from RESEARCH.
D6 invariant: asyncio.run() only. # FORBIDDEN: uvloop
Throttle: ≥30s between same-host attempts (RESEARCH §Pitfall 5 line 768).
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

# ── httpx import ─────────────────────────────────────────────────────────────
try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed — run: uv pip install httpx[http2]==0.28.1", file=sys.stderr)
    sys.exit(1)

# ── DEFAULT_HEADERS — VERBATIM from RESEARCH lines 623-638 (D11 invariant) ──
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="146", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.google.com/",
}

THROTTLE_SECONDS = 30  # ≥30s between same-host attempts (RESEARCH §Pitfall 5)
HOST_SLUGS = {
    "falabella": "falabella",
    "frog": "frog",
    "romero": "romero",
}

SCRIPT_DIR = Path(__file__).parent
ARTIFACTS_DIR = Path(__file__).parent.parent.parent / "artifacts" / "spike"


def load_urls(host: str) -> list[str]:
    """Load URLs for the given host slug."""
    url_file = SCRIPT_DIR / f"{host}_urls.txt"
    if not url_file.exists():
        print(f"ERROR: {url_file} not found", file=sys.stderr)
        print(f"Create it with ≥10 https:// lines for host '{host}'", file=sys.stderr)
        sys.exit(1)
    urls = []
    for line in url_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


async def probe_url(
    client: httpx.AsyncClient, idx: int, url: str
) -> dict:
    """Fire one GET, return result dict."""
    t0 = time.perf_counter()
    try:
        resp = await client.get(url)
        elapsed = time.perf_counter() - t0
        final_url = str(resp.url)
        byte_count = len(resp.content)
        return {
            "idx": idx,
            "url": url,
            "status": resp.status_code,
            "elapsed": elapsed,
            "final_url": final_url[:100],
            "byte_count": byte_count,
            "error": None,
        }
    except httpx.TimeoutException as e:
        elapsed = time.perf_counter() - t0
        return {"idx": idx, "url": url, "status": "timeout", "elapsed": elapsed,
                "final_url": None, "byte_count": 0, "error": f"TimeoutException: {str(e)[:80]}"}
    except httpx.NetworkError as e:
        elapsed = time.perf_counter() - t0
        return {"idx": idx, "url": url, "status": "network_error", "elapsed": elapsed,
                "final_url": None, "byte_count": 0, "error": f"NetworkError: {str(e)[:80]}"}
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return {"idx": idx, "url": url, "status": "error", "elapsed": elapsed,
                "final_url": None, "byte_count": 0, "error": f"{type(e).__name__}: {str(e)[:80]}"}


async def main(host: str) -> int:
    urls = load_urls(host)
    n = len(urls)
    if n < 10:
        print(f"WARNING: only {n} URLs for host '{host}' — need ≥10 for D11 validity")

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = ARTIFACTS_DIR / f"{host}_403.txt"

    results = []
    consecutive_5xx = 0

    print(f"[07_falabella_403] Probing host={host} with N={n} URLs")
    print(f"[07_falabella_403] DEFAULT_HEADERS: Sec-Fetch-Site=cross-site, Referer=google.com (D11 invariant)")

    async with httpx.AsyncClient(
        http2=True,
        headers=DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=10.0,
    ) as client:
        for idx, url in enumerate(urls, 1):
            result = await probe_url(client, idx, url)
            results.append(result)

            status = result["status"]
            elapsed = result["elapsed"]
            err = result.get("error") or ""

            if isinstance(status, int):
                print(f"[{idx:02d}] status={status} elapsed={elapsed:.2f}s bytes={result['byte_count']} final={result['final_url'] or url[:60]}")
                # Track consecutive 5xx for abort protection
                if 500 <= status < 600:
                    consecutive_5xx += 1
                else:
                    consecutive_5xx = 0
            else:
                print(f"[{idx:02d}] ERR={status} elapsed={elapsed:.2f}s err={err}")
                consecutive_5xx = 0

            # Abort on 3 consecutive 5xx (acceptance criterion)
            if consecutive_5xx >= 3:
                print(f"[07_falabella_403] ABORT: 3 consecutive 5xx detected — stopping to avoid IP-block escalation")
                # Write abort flag to artifact
                artifact_path.write_text(
                    f"aborted_after_3_consecutive_5xx: YES\n"
                    f"aborted_at_idx: {idx}\n",
                    encoding="utf-8"
                )
                break

            # Throttle: ≥30s between same-host attempts (RESEARCH §Pitfall 5)
            if idx < len(urls):
                print(f"[{idx:02d}]   Throttle: sleeping {THROTTLE_SECONDS}s...")
                await asyncio.sleep(THROTTLE_SECONDS)

    # ── Compute outcome statistics ────────────────────────────────────────────
    n_total = len(results)
    count_200 = sum(1 for r in results if r["status"] == 200)
    count_403 = sum(1 for r in results if r["status"] == 403)
    count_5xx = sum(1 for r in results if isinstance(r["status"], int) and 500 <= r["status"] < 600)
    count_timeout = sum(1 for r in results if r["status"] == "timeout")
    count_other = n_total - count_200 - count_403 - count_5xx - count_timeout

    success_rate = count_200 / n_total if n_total > 0 else 0.0

    # D11 verdict rules (RESEARCH lines 614-617 paraphrased for per-host probing):
    if success_rate >= 0.7:
        verdict = "realistic-headers-sufficient"
    elif success_rate < 0.5:
        verdict = "realistic-headers-insufficient"
    else:
        verdict = "borderline"

    # ── Write artifact ────────────────────────────────────────────────────────
    lines = []
    lines.append(f"## 403-rate probe: host={host} (N={n_total}, {THROTTLE_SECONDS}s spacing, httpx + DEFAULT_HEADERS)")
    lines.append(f"")
    lines.append(f"| N={n_total} | host | 200 | 403 | 5xx | timeout | other |")
    lines.append(f"|------|------|-----|-----|-----|---------|-------|")
    lines.append(f"| {n_total}   | {host} | {count_200} | {count_403} | {count_5xx} | {count_timeout} | {count_other} |")
    lines.append(f"")
    lines.append(f"conclusion: success rate={success_rate:.0%} ({count_200}/{n_total}) under bare httpx + Chromium-146 headers")
    lines.append(f"")
    lines.append(f"## Per-attempt detail")
    lines.append(f"")
    for r in results:
        status = r["status"]
        elapsed = r["elapsed"]
        err_suffix = f" err={r['error']}" if r["error"] else ""
        lines.append(f"| {r['idx']:02d} | {status} | {elapsed:.2f}s | {r['byte_count']}B | {(r['final_url'] or r['url'])[:60]}{err_suffix} |")
    lines.append(f"")
    lines.append(f"D11_VERDICT_{host}: {verdict}")
    lines.append(f"")
    if success_rate >= 0.7:
        lines.append(f"Phase 2 implication: DEFAULT_HEADERS sufficient for {host} — curl-cffi deferral to Phase 3 confirmed for this host.")
    elif success_rate < 0.5:
        if host == "falabella":
            lines.append(f"Phase 2 implication: Falabella Akamai WAF blocks httpx at {count_403}/N — expected per RESEARCH §Pattern 6. visit_failed flag for Falabella is realistic at MVP. curl-cffi deferred to Phase 3.")
        else:
            lines.append(f"Phase 2 implication: UNEXPECTED — {host} blocks httpx at {count_403}/N. Flag for Phase 3 priority escalation.")
    else:
        lines.append(f"Phase 2 implication: borderline ({success_rate:.0%}) — monitor in Phase 2; potential curl-cffi need.")

    artifact_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[07_falabella_403] Written: {artifact_path}")
    print(f"[07_falabella_403] D11_VERDICT_{host}: {verdict}")

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="httpx 403-rate probe for AR catalog hosts")
    parser.add_argument(
        "--host",
        default="falabella",
        choices=list(HOST_SLUGS.keys()),
        help="Host to probe (falabella | frog | romero)",
    )
    args = parser.parse_args()

    if args.host not in HOST_SLUGS:
        print(f"ERROR: unknown host '{args.host}'. Use: falabella | frog | romero", file=sys.stderr)
        sys.exit(2)

    sys.exit(asyncio.run(main(args.host)))
