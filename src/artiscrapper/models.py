"""
Pydantic v2 request/response models.
PRD §3 response shape: {query, results, metadata}
SearchRequest.query field name is "query" — NOT "q" (SEARCH-01).
Metadata has 9 fields: 8 from SEARCH-08 + block_detected (BROWSER-05).
"""
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=15, ge=1, le=30)
    visit_timeout_s: int = Field(default=10, ge=3, le=30)


class Candidate(BaseModel):
    url: str
    title: str | None = None
    snippet: str | None = None
    price: str | None = None
    currency: str | None = None
    has_price: bool = False
    fresh: bool | None = None
    llm_confidence: float = 0.0
    freshness_signal: str = "unknown"
    flags: list[str] = Field(default_factory=list)


class Metadata(BaseModel):
    # SEARCH-08: 8 required fields + block_detected (BROWSER-05) = 9 total
    elapsed_ms: int
    google_fetches: int = 2
    candidates_total: int = 0
    llm_filtered_out: int = 0
    visited: int = 0
    visit_failed: int = 0
    cache_hit: bool = False
    llm_degraded: bool = False
    block_detected: bool = False  # BROWSER-05: set true when _detect_block fires; defaults false


class SearchResponse(BaseModel):
    # PRD §3 response shape: {query, results, metadata}
    query: str  # echo of the request query (PRD §3)
    results: list[Candidate]
    metadata: Metadata
