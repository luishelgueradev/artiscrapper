"""
Process-singleton metrics — D-11 prometheus bridge over the Phase 2 inline
dataclass. The dataclass IS NOT removed (D-11: bridge, NOT replace) — every
wrapper writes to BOTH the legacy dataclass AND the prometheus Counter so
existing Phase 2 tests + readers continue to work.

Phase 3 additions (per 03-RESEARCH.md §A and 03-PATTERNS.md §"metrics.py"):
  - Default Python-VM collectors (GC/PLATFORM/PROCESS) unregistered so the
    /metrics export contains only artiscrapper_* families (§A2).
  - Three Counter families with the canonical names from D-11.
  - Three Histogram families per D-12 (search/llm/visit elapsed) with
    workload-tuned buckets (§A4).
  - Bridge wrappers inc_llm_fallback / inc_visit_failed / inc_block_detected
    that dual-write to dataclass + prometheus Counter.
  - Pre-seeding of known `reason` label values to avoid gappy /metrics
    output during the first scrape after a fresh boot (§A6 / Pitfall 10).

CRITICAL — D-12 + Pitfall 1 (03-RESEARCH.md §A5): Histogram.time() MUST be
used as a CONTEXT MANAGER inside async functions, NEVER as a decorator on
`async def` — the decorator measures coroutine creation, not awaited work.
"""

from collections import defaultdict
from dataclasses import dataclass, field

import tldextract
from prometheus_client import (
    GC_COLLECTOR,
    PLATFORM_COLLECTOR,
    PROCESS_COLLECTOR,
    REGISTRY,
    Counter,
    Histogram,
)

# ── Default-collector unregistration (§A2) ──
# Each unregister is wrapped in try/except KeyError so test re-imports
# (e.g., importlib.reload) tolerate the collector already being gone.
for _coll in (GC_COLLECTOR, PLATFORM_COLLECTOR, PROCESS_COLLECTOR):
    try:
        REGISTRY.unregister(_coll)
    except KeyError:
        pass  # already unregistered (test re-import); harmless


# ── Counter families (D-11 — canonical names from Phase 2) ──
llm_fallback_counter = Counter(
    "artiscrapper_llm_fallback_total",
    "LLM curator fallback verdicts emitted, by reason",
    ["reason"],
)
visit_failed_counter = Counter(
    "artiscrapper_visit_failed_total",
    "Visit-pass failures, by host (TLD+1 normalized)",
    ["host"],
)
block_detected_counter = Counter(
    "artiscrapper_block_detected_total",
    "Google block-detection events, by marker reason",
    ["reason"],
)


# ── Histogram families (D-12) ──
# Bucket choices justified in 03-RESEARCH.md §A4 against NF-01 budgets:
# P50 cache-hit <0.5s, P50 cold <20s, P95 cold <40s for /search;
# per-candidate LLM TTFT p95=344ms, batched 4-concurrent ~3-5s for 20 candidates;
# httpx fetch 1-5s, extract <100ms, classify <50ms for visit.
SEARCH_BUCKETS = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 40.0, 60.0, float("inf"))
LLM_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, float("inf"))
VISIT_BUCKETS = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, float("inf"))

search_elapsed = Histogram(
    "artiscrapper_search_elapsed_seconds",
    "End-to-end /search wall-clock",
    buckets=SEARCH_BUCKETS,
)
llm_elapsed = Histogram(
    "artiscrapper_llm_elapsed_seconds",
    "LLM curator batch latency (curate_candidates call)",
    buckets=LLM_BUCKETS,
)
visit_elapsed = Histogram(
    "artiscrapper_visit_elapsed_seconds",
    "Visit pass latency per stage",
    ["stage"],  # fetch | extract | classify
    buckets=VISIT_BUCKETS,
)


# ── Legacy dataclass (D-11 — bridge, NOT replace) ──
@dataclass
class Metrics:
    llm_fallback_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    visit_failed_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    browser_recycles_total: int = 0
    block_detected_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))


metrics = Metrics()  # process-singleton (safe with --workers 1)


# ── Bridge wrappers (D-11 — every Phase 2 call site routes through these) ──


def _host_for_metric(url_or_host: str) -> str:
    """
    Normalize a URL or host to TLD+1 to cap visit_failed cardinality at
    ~50 hosts even when SERPs surface m.example.com / www.example.com / etc.
    (§A6 — Counter cardinality limit is ~100 label values per dimension).
    """
    ext = tldextract.extract(url_or_host)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}"
    # Edge cases: empty host, IP-only URL, etc. — bucket under "unknown" so
    # the label still has a finite-cardinality default.
    return "unknown"


def inc_llm_fallback(reason: str) -> None:
    """D-11 dual-write: legacy dataclass + prometheus Counter."""
    metrics.llm_fallback_total[reason] += 1
    llm_fallback_counter.labels(reason=reason).inc()


def inc_visit_failed(url_or_host: str) -> None:
    """D-11 dual-write — host argument is normalized to TLD+1 (§A6)."""
    host = _host_for_metric(url_or_host)
    metrics.visit_failed_total[host] += 1
    visit_failed_counter.labels(host=host).inc()


def inc_block_detected(reason: str) -> None:
    """D-11 dual-write: legacy dataclass + prometheus Counter."""
    metrics.block_detected_total[reason] += 1
    block_detected_counter.labels(reason=reason).inc()


# ── Label pre-seeding (§A6 / Pitfall 10) ──
# Touching `.labels(...)` once at module load makes the time series appear in
# /metrics with value 0 immediately, so alerting/scraping doesn't see a
# "missing" series during the first scrape interval after a fresh boot.
# Only seed bounded enums (reason). DO NOT seed `host` for visit_failed —
# that label is unbounded and depends on which hosts are actually encountered.
for _reason in (
    "timeout",
    "overload",
    "malformed",
    "conn_error",
    "cold_load_502",
    "cold_load_504",
    "http_400",
    "http_500",
):
    llm_fallback_counter.labels(reason=_reason)

for _reason in (
    "consent_interstitial",
    "sorry",
    "recaptcha",
    "unknown",
):
    block_detected_counter.labels(reason=_reason)

# Usage notes (kept from Phase 2 — call sites in llm.py / visit.py / main.py
# now go through the bridge wrappers, not direct dict mutation):
#   inc_llm_fallback("timeout")            (LLM-04 fallback)
#   inc_llm_fallback("malformed")
#   inc_visit_failed("https://falabella.com.ar/...")  (VISIT-07 — wrapper
#                                            normalizes to "falabella.com.ar")
#   inc_block_detected("sorry")            (BROWSER-05)
