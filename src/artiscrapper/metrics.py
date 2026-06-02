"""
OBS-06 Inline counters (pre-Prometheus).
Pattern 13 from 02-RESEARCH.md (lines 1368-1389) — verbatim.
Process-singleton (safe with --workers 1).
Phase 3 wires these into prometheus-client.
"""
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Metrics:
    llm_fallback_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    visit_failed_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    browser_recycles_total: int = 0
    block_detected_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))


metrics = Metrics()  # process-singleton (safe with --workers 1)

# Usage:
# metrics.llm_fallback_total["timeout"] += 1       (LLM-04 fallback)
# metrics.llm_fallback_total["malformed"] += 1
# metrics.visit_failed_total["falabella.com.ar"] += 1  (VISIT-07)
# metrics.block_detected_total["sorry_redirect"] += 1  (BROWSER-05)
