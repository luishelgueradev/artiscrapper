#!/usr/bin/env python3
"""
03_pws_consent_probe.py — pws=0 consent-interstitial sweep + SERP fixture top-up.

Reads all existing fixtures from tests/fixtures/serp/*.html, analyzes them for
INTERSTITIAL_MARKERS and structural sanity (size, h3 presence), and optionally
captures additional fixtures if the count is below 10.

References:
  01-RESEARCH.md §Pattern 1 (lines 267-322) — browser/context scaffold
  01-RESEARCH.md §Pitfall 2 (lines 747-751) — pws=0 interstitial risk
  01-RESEARCH.md §Anti-Patterns (line 712) — ≤1/min SERP throttle
  01-VALIDATION.md §Per-Task Verification Map row AC-3

Exit codes:
  0 — no consent markers found on any fixture (D3 clean)
  1 — interstitial markers found on ≥1 fixture (D3 pivot — Phase 2 needs cookie-banner-dismissal)
  2 — missing prerequisites (env issue)
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import cloakbrowser
from selectolax.parser import HTMLParser

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

# Abort capture if 3 consecutive fetches hit block markers (T-01-01-03)
CONSECUTIVE_BLOCK_ABORT = 3

# ── D8 invariant guard ─────────────────────────────────────────────────────
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

# ── D6 invariant reminder — asyncio only ────────────────────────────────────
# asyncio.run(main()) — NEVER uvloop.install()


def analyze_fixture(html: str, filename: str) -> dict:
    """Analyze a single SERP HTML fixture for interstitial markers and structure."""
    hits = [m for m in INTERSTITIAL_MARKERS if m in html]
    byte_count = len(html.encode("utf-8"))
    size_kb = byte_count / 1024

    tree = HTMLParser(html)
    h3_count = len(tree.css("h3"))

    is_likely_interstitial = (size_kb < 30) or (h3_count == 0 and size_kb < 100)

    if size_kb < 35:
        print(f"WARNING: fixture {filename} only {size_kb:.1f}KB — likely consent stub")

    return {
        "filename": filename,
        "bytes": byte_count,
        "size_kb": round(size_kb, 1),
        "marker_hits": hits,
        "h3_count": h3_count,
        "is_likely_interstitial": is_likely_interstitial,
    }


async def top_up_fixtures(out_dir: Path, existing_count: int, target: int = 10) -> list[dict]:
    """Capture additional SERP fixtures until we reach target count."""
    if existing_count >= target:
        print(f"[03] Already have {existing_count} fixtures — skip capture")
        return []

    needed = target - existing_count
    print(f"[03] Need {needed} more fixtures (current: {existing_count}, target: {target})")

    # Determine which queries haven't been captured yet
    existing_files = [f.name for f in out_dir.glob("*.html")]
    # Map existing slugs back to query indices
    captured_indices = set()
    for i, q in enumerate(QUERIES):
        slug = q.replace(" ", "_").replace("/", "_")
        if any(slug in f for f in existing_files):
            captured_indices.add(i)

    remaining_queries = [(i, q) for i, q in enumerate(QUERIES) if i not in captured_indices]
    queries_to_run = remaining_queries[:needed]

    if not queries_to_run:
        print("[03] All queries already captured")
        return []

    results = []
    consecutive_blocks = 0

    browser = await cloakbrowser.launch_async(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    manifest_path = out_dir / "MANIFEST.md"

    for orig_idx, q in queries_to_run:
        file_idx = existing_count + len(results) + 1
        ctx = await browser.new_context(
            locale="es-AR",
            timezone_id="America/Argentina/Buenos_Aires",
            viewport={"width": 1366, "height": 768},
        )
        page = await ctx.new_page()
        url = GOOGLE.format(q=q.replace(" ", "+"))

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            html = await page.content()
            hits = [m for m in INTERSTITIAL_MARKERS if m in html]
            byte_count = len(html.encode("utf-8"))
            slug = q.replace(" ", "_").replace("/", "_")
            out_path = out_dir / f"{file_idx:02d}-{slug}.html"
            out_path.write_text(html, encoding="utf-8")

            if "/sorry/index" in hits or 'g-recaptcha' in hits:
                consecutive_blocks += 1
                if consecutive_blocks >= CONSECUTIVE_BLOCK_ABORT:
                    print(f"WARNING: 3 consecutive blocks — aborting capture (T-01-01-03)")
                    await ctx.close()
                    await browser.close()
                    break
            else:
                consecutive_blocks = 0

            captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            marker_str = ", ".join(hits) if hits else "none"
            size_kb = byte_count / 1024

            with manifest_path.open("a", encoding="utf-8") as mf:
                mf.write(f"| {out_path.name} | \"{q}\" | {byte_count} | {marker_str} | {captured_at} |\n")

            if size_kb < 35:
                print(f"WARNING: fixture {out_path.name} only {size_kb:.1f}KB — likely consent stub")

            print(f"[{file_idx:02d}] q='{q}' hits={hits} bytes={byte_count} ({size_kb:.0f}KB)")
            results.append(analyze_fixture(html, out_path.name))

        except Exception as e:
            print(f"[{file_idx:02d}] ERROR: {e}")

        await page.close()
        await ctx.close()

        if len(results) < needed:
            print("[03] Throttle: sleeping 60s...")
            await asyncio.sleep(60)

    await browser.close()
    return results


def analyze_all_fixtures(out_dir: Path) -> dict:
    """Scan all fixtures and produce aggregate stats."""
    fixtures = sorted(out_dir.glob("*.html"))
    if not fixtures:
        return {"total_fixtures": 0, "error": "no fixtures found"}

    results = []
    for f in fixtures:
        html = f.read_text(encoding="utf-8")
        results.append(analyze_fixture(html, f.name))

    total = len(results)
    with_any_marker = sum(1 for r in results if r["marker_hits"])
    per_marker_hits = {}
    for r in results:
        for m in r["marker_hits"]:
            per_marker_hits[m] = per_marker_hits.get(m, 0) + 1
    sizes_kb = [r["size_kb"] for r in results]
    mean_size = round(sum(sizes_kb) / len(sizes_kb), 1)
    min_size = min(sizes_kb)
    max_size = max(sizes_kb)
    likely_interstitial = sum(1 for r in results if r["is_likely_interstitial"])

    return {
        "total_fixtures": total,
        "with_any_marker": with_any_marker,
        "per_marker_hit_counts": per_marker_hits,
        "mean_size_kb": mean_size,
        "min_size_kb": min_size,
        "max_size_kb": max_size,
        "likely_interstitial_count": likely_interstitial,
        "results": results,
    }


async def main() -> None:
    out_dir = Path("tests/fixtures/serp")
    artifact_dir = Path("artifacts/spike")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Count existing fixtures
    existing = list(out_dir.glob("*.html"))
    existing_count = len(existing)
    print(f"[03] Existing fixtures: {existing_count}")

    # Top up to 10 if needed (tasks 2 already ran 10 but may be re-running)
    if existing_count < 10:
        new_results = await top_up_fixtures(out_dir, existing_count, target=10)
    else:
        print(f"[03] Already have {existing_count} fixtures — analysis only")

    # Analyze all fixtures on disk
    print("[03] Analyzing all fixtures for consent markers...")
    stats = analyze_all_fixtures(out_dir)
    total = stats["total_fixtures"]
    with_any = stats["with_any_marker"]
    mean_kb = stats["mean_size_kb"]
    min_kb = stats["min_size_kb"]
    max_kb = stats["max_size_kb"]

    print(f"[03] total_fixtures: {total}")
    print(f"[03] with_any_marker: {with_any}")
    print(f"[03] per_marker_hits: {stats['per_marker_hit_counts']}")
    print(f"[03] mean_size_kb: {mean_kb}")
    print(f"[03] min_size_kb: {min_kb}")
    print(f"[03] max_size_kb: {max_kb}")
    print(f"[03] likely_interstitial_count: {stats['likely_interstitial_count']}")

    # Write summary artifact
    summary_path = artifact_dir / "pws_consent_summary.txt"
    with summary_path.open("w", encoding="utf-8") as f:
        f.write("# pws=0 Consent Interstitial Summary\n")
        f.write(f"# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n")
        f.write(f"total_fixtures: {total}\n")
        f.write(f"with_any_marker: {with_any}\n")
        f.write(f"per_marker_hit_counts: {stats['per_marker_hit_counts']}\n")
        f.write(f"mean_size_kb: {mean_kb}\n")
        f.write(f"min_size_kb: {min_kb}\n")
        f.write(f"max_size_kb: {max_kb}\n")
        f.write(f"likely_interstitial_count: {stats['likely_interstitial_count']}\n")
        f.write("\n")
        f.write("## Per-fixture\n")
        f.write("| filename | size_kb | h3_count | marker_hits |\n")
        f.write("|----------|---------|----------|-------------|\n")
        for r in stats.get("results", []):
            marker_str = ", ".join(r["marker_hits"]) if r["marker_hits"] else "none"
            f.write(f"| {r['filename']} | {r['size_kb']} | {r['h3_count']} | {marker_str} |\n")
        f.write("\n")

        # D3 verdict (required: must have exactly one ^D3_VERDICT: line)
        if with_any == 0 and min_kb >= 100 and stats["likely_interstitial_count"] == 0:
            verdict = f"D3_VERDICT: clean — no consent interstitial observed on N={total} cold-context fetches"
        else:
            pivot_reason = []
            if with_any > 0:
                pivot_reason.append(f"{with_any} fixtures have interstitial markers")
            if min_kb < 35:
                pivot_reason.append(f"min fixture size {min_kb}KB < 35KB")
            if stats["likely_interstitial_count"] > 0:
                pivot_reason.append(f"{stats['likely_interstitial_count']} likely interstitial pages")
            verdict = f"D3_VERDICT: pivot — interstitial observed on {with_any}/{total} fetches; Phase 2 must add cookie-banner-dismissal"

        f.write(f"{verdict}\n")

    print(f"[03] Summary written to {summary_path}")
    print(f"\n{verdict}")

    # Append aggregate block to MANIFEST.md
    manifest_path = out_dir / "MANIFEST.md"
    if manifest_path.exists():
        with manifest_path.open("a", encoding="utf-8") as mf:
            mf.write("\n## Aggregate\n\n")
            mf.write(f"| total_fixtures | with_any_marker | mean_size_kb | min_size_kb | max_size_kb |\n")
            mf.write(f"|----------------|-----------------|--------------|-------------|-------------|\n")
            mf.write(f"| {total} | {with_any} | {mean_kb} | {min_kb} | {max_kb} |\n")
            mf.write(f"\n{verdict}\n")

    # Exit code based on D3 verdict
    if "clean" in verdict:
        sys.exit(0)
    else:
        sys.exit(1)  # pivot needed — non-fatal, spike records


if __name__ == "__main__":
    asyncio.run(main())
