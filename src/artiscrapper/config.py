"""
Configuration module — pydantic-settings BaseSettings.
All tunable params via env vars with typed defaults.
LLM_ROUTER_BEARER_TOKEN has NO default — startup fails without it (RESEARCH.md §Environment).
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    VERSION: str = "0.1.1"
    CACHE_DB_PATH: str = "/app/cache.db"
    HEADLESS: bool = True
    # BROWSER-04 (Path B perf-audit 2026-06-04): minimum seconds between Google
    # fetches inside a SINGLE /search request. Was 60 — empirically that adds
    # ~60s of dead sleep to every cold path (the second of 2 paralleled fetches
    # waits for the gate). Default bumped to 0 because the slowapi consumer
    # rate-limit on /search is the primary defense against burst-induced Google
    # blocks. See .planning/PERFORMANCE-AUDIT-2026-06-04.md §1, §4.
    GOOGLE_MIN_INTERVAL_S: int = 0
    BROWSER_RECYCLE_AFTER: int = 200
    LLM_ROUTER_URL: str = "http://127.0.0.1:3210"
    LLM_ROUTER_BEARER_TOKEN: (
        str  # no default — pydantic raises ValidationError at startup if absent
    )
    # Fallback model alias — used only if recommendations lookup is disabled or
    # fails. Set to the local-llms canonical alias for chat+json_strict, which
    # routes to qwen2.5:7b-instruct-q4_K_M as of 2026-06-03.
    LLM_MODEL: str = "chat-local"
    # When True (default), boot reads /v1/models recommendations[LLM_RECOMMENDATION_KEY]
    # and pins it for the process lifetime. Falls back to LLM_MODEL on any error.
    # Set to False to bypass the lookup (e.g. in tests, or to force a specific alias).
    LLM_USE_RECOMMENDATIONS: bool = True
    LLM_RECOMMENDATION_KEY: str = "chat-json-strict-default"
    # Backoff for single retry on 502/504 (upstream cold-load / adapter timeout).
    # Local-llms-router cancels at ~45s; qwen2.5:7b cold-load is ~50s on 16GB GPU.
    # KEEP_ALIVE=-1 on the router keeps it hot, so this almost never fires.
    LLM_COLD_LOAD_RETRY_AFTER_S: float = 30.0
    # LLM-03 (Path B perf-audit 2026-06-04): per-request concurrency against the
    # local LLM router. Was 4 — empirically sem(4) and sem(2) give the same
    # throughput against local-llms-router (speedup 1.47x in both cases), so 4
    # left ~half the available router parallelism on the table. Default bumped
    # to 8 to maximize throughput without saturating OpenWebUI / other shared
    # consumers (sem 16 is the empirical maximum but reserves no headroom for
    # the rest of the local-llms stack). See PERFORMANCE-AUDIT §1 / §4.
    LLM_CONCURRENCY: int = 8
    LOG_JSON: bool = True
    LOG_LEVEL: str = "INFO"

    # ── Phase 3 — Robustness ──
    # D-01: comma-separated API keys; empty string means "no auth configured"
    # (auth.py warns at module load when empty). Rotation requires container restart.
    API_KEYS: str = ""
    # D-02: per-key quotas. The slowapi decorators use string literals
    # ("60/minute" / "10000/day") so these constants exist mainly for the D-19
    # lifespan log line and for documentation; they are not threaded into the
    # decorator strings (per Pitfall 6 in 03-RESEARCH.md — settings/contract
    # shadowing risk).
    API_RATE_PER_MINUTE: int = 60
    API_RATE_PER_DAY: int = 10000
    # D-14: empty → Sentry disabled (no init). Set in production compose only.
    SENTRY_DSN: str = ""
    # Phase 0.2.2 HARNESS-03: fraction (0.0..1.0) of /search requests sampled
    # for parity audit on the hot path. Each sampled request reuses the HTML
    # already produced by the pipeline (no extra Cloak fetch) and runs the
    # parser metric helper in a fire-and-forget bg task — overhead is
    # <50ms p99 on a 1.5 MB SERP HTML. Set to 0.0 to disable the sample.
    PARITY_SAMPLE_RATE: float = 0.1

    @field_validator("PARITY_SAMPLE_RATE")
    @classmethod
    def _validate_parity_sample_rate(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(
                f"PARITY_SAMPLE_RATE must be in [0.0, 1.0], got {v!r}"
            )
        return v

    # ── Phase 0.2.3 — Paginación Page 2 (PAGE2-01) ──
    # Number of SERP pages fetched per /search call. Each page costs 2 Cloak
    # browser contexts (one for the non-meli URL, one for +mercadolibre).
    # Default 2 — adds ~25-40% latency p50 in exchange for +10-40 unique
    # candidates on queries with shopping-panel saturation (electro, ropa,
    # libro). Set to 1 to revert to v0.2.2 single-page behavior without a
    # redeploy. Cap is 3 (BROWSER_RECYCLE_AFTER + CAPTCHA-risk safety).
    SEARCH_FETCH_PAGES: int = 2

    @field_validator("SEARCH_FETCH_PAGES")
    @classmethod
    def _validate_search_fetch_pages(cls, v: int) -> int:
        if not 1 <= v <= 3:
            raise ValueError(f"SEARCH_FETCH_PAGES must be in [1, 3], got {v}")
        return v

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()  # type: ignore[call-arg]  # pydantic-settings reads LLM_ROUTER_BEARER_TOKEN from env
