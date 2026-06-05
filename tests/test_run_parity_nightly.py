"""Phase 0.2.2 HARNESS-04 — tests for the nightly script's aggregation logic.

Pure unit tests on `_row` and `_to_markdown`. Doesn't touch HTTP or YAML
parsing — those are integration concerns covered by manual CI dry-run.
"""
import sys
from pathlib import Path

# Make `scripts/` importable without installing the project as a package
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.run_parity_nightly import _row, _to_markdown


def _entry(id_: str, expected: int) -> dict:
    return {
        "id": id_,
        "query": f"{id_} query",
        "vertical": "test",
        "specificity": "espec",
        "min_expected_real_urls": expected,
    }


def test_row_ok_status_when_coverage_above_50():
    """Coverage >= 50 → status OK."""
    resp = {"blocked": False, "parser_metrics": {"candidates_real_url": 8}}
    row = _row(_entry("ok", 10), resp, None)
    assert row["status"] == "OK"
    assert row["coverage_pct"] == 80.0
    assert row["real_urls"] == 8
    assert row["expected"] == 10


def test_row_low_status_when_coverage_below_50():
    """Coverage < 50 → status LOW."""
    resp = {"blocked": False, "parser_metrics": {"candidates_real_url": 2}}
    row = _row(_entry("low", 10), resp, None)
    assert row["status"] == "LOW"
    assert row["coverage_pct"] == 20.0


def test_row_blocked_query():
    """Blocked response → status BLOCKED:..."""
    resp = {"blocked": "captcha_form"}
    row = _row(_entry("blocked", 10), resp, None)
    assert row["status"].startswith("BLOCKED")
    assert "captcha_form" in row["status"]
    assert row["coverage_pct"] is None


def test_row_error_query():
    """Network error → status ERROR:..."""
    row = _row(_entry("err", 10), None, "connection refused")
    assert row["status"].startswith("ERROR")
    assert "connection refused" in row["status"]
    assert row["coverage_pct"] is None


def test_markdown_table_includes_header_and_rows():
    """The markdown must have a heading + every row id + threshold."""
    rows = [
        {
            "id": "x",
            "vertical": "v",
            "spec": "espec",
            "real_urls": 5,
            "expected": 10,
            "coverage_pct": 50.0,
            "status": "OK",
        }
    ]
    md = _to_markdown(rows, 50.0, 75.0)
    assert "| id |" in md
    assert "| x |" in md
    assert "50.0%" in md
    assert "75%" in md
