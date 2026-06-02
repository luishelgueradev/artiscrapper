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
    # Default model name targets the current local-llms-router deploy. Phase 1
    # SPIKE used "chat-local"; the router has since migrated to explicit ollama
    # tags (no alias). Override via env when targeting a different backend.
    LLM_MODEL: str = "llama3.2:3b-instruct-q4_K_M"
    LLM_CONCURRENCY: int = 4  # empirically confirmed Phase 1 (N=4: 4/4 200, mean=0.81s)
    LOG_JSON: bool = True
    LOG_LEVEL: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()  # type: ignore[call-arg]  # pydantic-settings reads LLM_ROUTER_BEARER_TOKEN from env
