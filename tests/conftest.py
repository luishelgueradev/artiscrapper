"""
Shared test fixtures.
Pattern 1 test override block from 02-RESEARCH.md (lines 404-420).
asyncio_mode="auto" is set in pyproject.toml — no need for @pytest.mark.asyncio.
"""

from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from src.artiscrapper.cache import PRAGMAS, init_schema


@pytest.fixture
def mock_app_state(tmp_path):
    """
    Override app.state for tests that don't need a real browser or cache.
    Cannot import main.app here due to LLM_ROUTER_BEARER_TOKEN requirement at import time.
    Use this fixture directly in handler tests.
    """
    state = MagicMock()
    state.browser = MagicMock()
    state.browser.is_connected.return_value = True
    state.cache = AsyncMock()  # aiosqlite connection mock
    state.browser_uses = 0
    state.rate_limit = MagicMock()
    state.rate_limit.acquire = AsyncMock()
    yield state


@pytest.fixture
async def tmp_db(tmp_path):
    """
    Temporary aiosqlite database with WAL PRAGMAS and schema initialized.
    Uses tmp_path (real file) to support WAL mode — :memory: does not support WAL.
    """
    db_path = str(tmp_path / "cache.db")
    db = await aiosqlite.connect(db_path)
    for pragma in PRAGMAS:
        await db.execute(pragma)
    await db.commit()
    await init_schema(db)
    yield db
    await db.close()


@pytest.fixture
def mock_browser():
    """Mock Cloakbrowser Browser object."""
    browser = MagicMock()
    browser.is_connected.return_value = True
    return browser
