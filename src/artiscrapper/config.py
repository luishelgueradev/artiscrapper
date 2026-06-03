"""
Configuration module — pydantic-settings BaseSettings.
All tunable params via env vars with typed defaults.
LLM_ROUTER_BEARER_TOKEN has NO default — startup fails without it (RESEARCH.md §Environment).
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    VERSION: str = "0.1.0"
    CACHE_DB_PATH: str = "/app/cache.db"
    HEADLESS: bool = True
    GOOGLE_MIN_INTERVAL_S: int = 60
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
    LLM_CONCURRENCY: int = 4  # empirically confirmed Phase 1 (N=4: 4/4 200, mean=0.81s)
    LOG_JSON: bool = True
    LOG_LEVEL: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()  # type: ignore[call-arg]  # pydantic-settings reads LLM_ROUTER_BEARER_TOKEN from env
