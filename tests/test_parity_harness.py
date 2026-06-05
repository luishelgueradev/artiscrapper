"""Phase 0.2.2 (HARNESS-01, HARNESS-02) — Dataset schema + parity-metric helper unit tests."""
from pathlib import Path

import yaml

from src.artiscrapper.main import _PARITY_DATASET, _compute_parity_metrics
from src.artiscrapper.metrics import parity_pla_units_missed

DATASET_PATH = Path(__file__).parent / "fixtures" / "parity-dataset.yaml"


def test_dataset_yaml_loads_and_validates_schema():
    """All 12 queries must carry the required schema fields with non-empty values."""
    d = yaml.safe_load(DATASET_PATH.read_text())
    # version bumps when baselines are recalibrated from a nightly run
    # (v1 = initial 2026-06-05 with 7 placeholders; v2 = recalibrated from
    # first nightly). The test only enforces presence + monotonicity, not
    # a specific value.
    assert isinstance(d["version"], int) and d["version"] >= 1
    assert isinstance(d["queries"], list)
    assert len(d["queries"]) == 12, f"Expected exactly 12 queries, got {len(d['queries'])}"
    required = {"id", "query", "vertical", "specificity", "min_expected_real_urls"}
    seen_ids = set()
    for q in d["queries"]:
        missing = required - set(q.keys())
        assert not missing, f"Query {q.get('id')!r} missing fields: {missing}"
        assert q["query"].strip(), f"Empty query for {q['id']}"
        assert isinstance(q["min_expected_real_urls"], int)
        assert q["min_expected_real_urls"] > 0
        assert q["specificity"] in ("espec", "broad")
        seen_ids.add(q["id"])
    assert len(seen_ids) == 12, "Duplicate query IDs"


def test_dataset_loaded_into_main_module():
    """Module-level loader populated _PARITY_DATASET dict at import."""
    assert len(_PARITY_DATASET) == 12
    assert "figura coleccion robotech" in _PARITY_DATASET
    assert _PARITY_DATASET["figura coleccion robotech"]["min_expected_real_urls"] == 9


def test_set_parity_metrics_computes_coverage_pct_correctly():
    """When query is in dataset, coverage_pct = 100 * real_urls / min_expected (clamped)."""
    cands = [
        {"url": "https://mercadolibre.com.ar/x", "flags": ["pla_unit"]},
        {"url": "https://mercadolibre.com.ar/y", "flags": ["pla_unit"]},
        {"url": "https://google.com/search?q=z", "flags": ["carousel"]},
    ]
    out = _compute_parity_metrics(
        "figura coleccion robotech", "fake html", cands, pla_nodes_count=2
    )
    # baseline 9, 2 real → 22.22%
    assert out["coverage_pct"] is not None
    assert abs(out["coverage_pct"] - (200.0 / 9.0)) < 0.01
    # url_synthetic_ratio: 1 synthetic of 3 cands_with_url
    assert abs(out["url_synthetic_ratio"] - (1.0 / 3.0)) < 0.001


def test_set_parity_metrics_increments_missed_counter():
    """pla_units_missed counter rises when html has more pla than parser extracted."""
    before = parity_pla_units_missed.labels(query="counter test")._value.get()
    cands = [{"url": "https://x.com/p", "flags": ["pla_unit"]}]
    out = _compute_parity_metrics("counter test", "html", cands, pla_nodes_count=5)
    assert out["pla_units_missed"] == 4
    after = parity_pla_units_missed.labels(query="counter test")._value.get()
    assert after == before + 4


def test_set_parity_metrics_handles_unknown_query_gracefully():
    """Queries not in dataset get None coverage_pct but still update other metrics."""
    out = _compute_parity_metrics("some unknown query xyz", "html", [], pla_nodes_count=0)
    assert out["coverage_pct"] is None
    assert out["pla_units_missed"] == 0
    assert out["url_synthetic_ratio"] == 0.0
