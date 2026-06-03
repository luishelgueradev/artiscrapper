"""
Phase 3 integration suite — shared fixtures.

Inherits `tmp_db` and `mock_app_state` from the parent `tests/conftest.py`
(pytest auto-discovers conftest at every parent level).

Phase 3-specific helpers added here:
  - load_labelled_jsonl: parse the 50-record Phase 1 SERP-candidate set.
  - reset_challenge_backoff_state: autouse fixture that resets the
    module-level `_STATE` between tests (challenge_backoff is a singleton).
    Wrapped in try/except ImportError so this conftest tolerates
    challenge_backoff.py not existing yet (Plan 03-02 ships it).
"""

import json
import pathlib

import pytest


@pytest.fixture
def load_labelled_jsonl() -> list[dict]:
    """Load the 50-record Phase 1 labelled SERP-candidate set."""
    path = (
        pathlib.Path(__file__).parent.parent
        / "fixtures"
        / "llm"
        / "labelled.jsonl"
    )
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.fixture(autouse=True)
def reset_challenge_backoff_state():
    """
    Reset the module-level `_STATE` singleton between tests so module-level
    caches don't bleed across test runs. challenge_backoff.py is owned by
    Plan 03-02 and may not exist yet — tolerate the ImportError gracefully.
    """
    try:
        from src.artiscrapper import challenge_backoff as cb  # type: ignore[import-not-found]

        cb._STATE = None
        yield
        cb._STATE = None
    except ImportError:
        # Plan 03-02 hasn't shipped challenge_backoff.py yet — no state to reset.
        yield
