#!/usr/bin/env python3
"""Phase 0.2.2 HARNESS-04 — CLI runner for the canonical parity dataset.

Loops over the dataset YAML, hits `/admin/parity/{query}` for each entry,
aggregates per-query coverage_pct, prints a markdown summary, and exits
non-zero when the average breaches the threshold OR any query was blocked.

Usage:
  python scripts/run_parity_nightly.py \\
    --dataset tests/fixtures/parity-dataset.yaml \\
    --endpoint http://localhost:8001/admin/parity \\
    --api-key "$ARTISCRAPPER_NIGHTLY_KEY" \\
    --threshold 75 \\
    --summary out.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib import parse as urlparse
from urllib import request as urlrequest


def _http_get_json(url: str, api_key: str, timeout: int = 60) -> dict[str, Any]:
    """GET with X-API-Key, parse JSON body. Raises on non-2xx."""
    req = urlrequest.Request(url, headers={"X-API-Key": api_key})
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _run_query(endpoint: str, query: str, api_key: str) -> dict[str, Any]:
    """Build the full URL (with FastAPI path quoting) and call _http_get_json."""
    url = endpoint.rstrip("/") + "/" + urlparse.quote(query)
    return _http_get_json(url, api_key)


def _row(
    entry: dict[str, Any],
    resp: dict[str, Any] | None,
    err: str | None,
) -> dict[str, Any]:
    """Reduce a (dataset entry, /admin/parity response, error?) into a flat
    row dict for tabular rendering + aggregation."""
    if err:
        return {
            "id": entry["id"],
            "vertical": entry["vertical"],
            "spec": entry["specificity"],
            "real_urls": "—",
            "expected": entry["min_expected_real_urls"],
            "coverage_pct": None,
            "status": f"ERROR: {err}",
        }
    if resp and resp.get("blocked"):
        return {
            "id": entry["id"],
            "vertical": entry["vertical"],
            "spec": entry["specificity"],
            "real_urls": "—",
            "expected": entry["min_expected_real_urls"],
            "coverage_pct": None,
            "status": f"BLOCKED: {resp.get('blocked')}",
        }
    assert resp is not None  # for type checkers — handled above
    real = resp.get("parser_metrics", {}).get("candidates_real_url", 0)
    expected = entry["min_expected_real_urls"]
    coverage_pct = (
        min(100.0, 100.0 * real / float(expected)) if expected else None
    )
    status = (
        "OK"
        if coverage_pct is not None and coverage_pct >= 50.0
        else "LOW"
    )
    return {
        "id": entry["id"],
        "vertical": entry["vertical"],
        "spec": entry["specificity"],
        "real_urls": real,
        "expected": expected,
        "coverage_pct": coverage_pct,
        "status": status,
    }


def _to_markdown(
    rows: list[dict[str, Any]],
    avg: float | None,
    threshold: float,
) -> str:
    """Render rows + summary stats as a GitHub-flavored markdown report."""
    lines = [
        "# Parity nightly audit",
        "",
        (
            f"Average coverage: **{avg:.1f}%**"
            if avg is not None
            else "Average coverage: —"
        ),
        f"Threshold: **{threshold:.0f}%**",
        "",
        "| id | vertical | spec | real_urls | expected | coverage_pct | status |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for r in rows:
        cov = (
            f"{r['coverage_pct']:.1f}%"
            if r["coverage_pct"] is not None
            else "—"
        )
        lines.append(
            f"| {r['id']} | {r['vertical']} | {r['spec']} | "
            f"{r['real_urls']} | {r['expected']} | {cov} | {r['status']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import yaml  # lazy import so tests can stub the function w/o pyyaml on path

    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, help="YAML dataset path")
    parser.add_argument(
        "--endpoint", required=True, help="Base URL for /admin/parity"
    )
    parser.add_argument("--api-key", required=True, help="X-API-Key value")
    parser.add_argument("--threshold", type=float, default=75.0)
    parser.add_argument(
        "--summary",
        help="Optional file to write the markdown summary to",
    )
    args = parser.parse_args(argv)

    d = yaml.safe_load(Path(args.dataset).read_text())
    rows: list[dict[str, Any]] = []
    blocked_any = False
    for entry in d.get("queries") or []:
        try:
            resp = _run_query(args.endpoint, entry["query"], args.api_key)
            time.sleep(1.0)  # polite spacing — respect GoogleRateLimiter
            err = None
        except Exception as exc:  # noqa: BLE001
            resp, err = None, str(exc)
        row = _row(entry, resp, err)
        if row["status"].startswith("BLOCKED"):
            blocked_any = True
        rows.append(row)

    covs = [r["coverage_pct"] for r in rows if r["coverage_pct"] is not None]
    avg = sum(covs) / len(covs) if covs else None
    md = _to_markdown(rows, avg, args.threshold)
    print(md)
    if args.summary:
        Path(args.summary).write_text(md)

    if blocked_any:
        print("FAIL: at least one query returned blocked", file=sys.stderr)
        return 1
    if avg is None:
        print("FAIL: no coverage measurements", file=sys.stderr)
        return 1
    if avg < args.threshold:
        print(
            f"FAIL: avg coverage {avg:.1f}% < threshold {args.threshold:.0f}%",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
