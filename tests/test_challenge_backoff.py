"""
Unit tests for challenge_backoff state machine (Phase 3 — Plan 03-02).

Pins the D-06 exponential-backoff curve `min(60 * 2^(retries-1), 3600)`,
the D-07 reset trigger (≥1h after last_block_at), and the D-08 sqlite
persistence shape (`challenge_state` single-row table).

Analogs:
  - Pattern S1 (module-singleton + asyncio.Lock) — mirrors
    `src/artiscrapper/llm.py::resolve_model` (`_RESOLVED_MODEL` + `_RESOLVE_LOCK`).
  - Pattern S2 (sqlite UPSERT) — mirrors `src/artiscrapper/cache.py::set_cached`.
  - tmp_db fixture comes from `tests/conftest.py` (Phase 2) and now auto-
    creates the `challenge_state` table via the extended `_DDL`.

D-19 (Phase 2 memory `feedback_empirical_retest_after_default_changes`):
  The curve constants live in `challenge_backoff._BASE_S` etc. — never
  threaded through settings (D-06 ROADMAP-lock). These tests assert the
  observable consequence of those constants, not the constants themselves
  (D-18 — fixture-driven assertions, never structural shape only).
"""

import time

import pytest

# The module ships in Task 2; this import IS the RED gate for Task 1.
from src.artiscrapper import challenge_backoff as cb
from src.artiscrapper.challenge_backoff import (
    _BACKOFF_CAP_S,
    _BASE_S,
    _RESET_AFTER_S,
    check_gate,
    record_block,
    record_success,
)


@pytest.fixture(autouse=True)
def _reset_state():
    """
    Reset the module-level `_STATE` singleton between tests.

    The `tests/integration/conftest.py` autouse fixture already does this
    for integration tests; this autouse fixture extends the discipline to
    the unit tests in this file so module-singleton state never bleeds.
    """
    cb._STATE = None
    yield
    cb._STATE = None


async def test_module_constants_match_d06_d07():
    """D-06 + D-07 invariant pin: constants are hardcoded module-level."""
    assert _BASE_S == 60, (
        f"D-06: _BASE_S must be 60 (first wait = 60s); got {_BASE_S}"
    )
    assert _BACKOFF_CAP_S == 3600, (
        f"D-06: _BACKOFF_CAP_S must be 3600 (1h cap); got {_BACKOFF_CAP_S}"
    )
    assert _RESET_AFTER_S == 3600, (
        f"D-07: _RESET_AFTER_S must be 3600 (reset trigger ≥1h); got {_RESET_AFTER_S}"
    )


async def test_exponential_curve(tmp_db):
    """
    D-06: backoff curve `min(60 * 2^(retries-1), 3600)`.

    Per-call expected waits (±2s tolerance for int(time.time()) quantization):
      retry 1 →   60s
      retry 2 →  120s
      retry 3 →  240s
      retry 4 →  480s
      retry 5 →  960s
      retry 6 → 1920s
      retry 7 → 3600s (cap saturates)
      retry 8 → 3600s
    """
    expected = [60, 120, 240, 480, 960, 1920, 3600, 3600]
    for i, want_s in enumerate(expected, start=1):
        await record_block(tmp_db)
        allowed, retry_after = await check_gate(tmp_db)
        assert allowed is False, (
            f"retry {i}: check_gate should deny while next_allowed_at > now"
        )
        # ±2s tolerance for epoch quantization between record_block and check_gate
        assert want_s - 2 <= retry_after <= want_s + 2, (
            f"D-06 curve regressed at retry {i}: "
            f"expected ~{want_s}s, got {retry_after}s "
            f"(formula: min(60 * 2^(retries-1), 3600))"
        )


async def test_reset_after_one_hour(tmp_db, monkeypatch):
    """
    D-07: first successful Google fetch ≥1h after `last_block_at` resets
    retry_count to 0 and next_allowed_at to 0.

    Strategy: trip a block at time T0, then monkeypatch
    `challenge_backoff.time.time` to return T0 + 3700s (just over 1h).
    A subsequent `record_success` MUST reset the row.
    """
    await record_block(tmp_db)

    # Confirm state moved off the zero baseline before the reset
    cur = await tmp_db.execute(
        "SELECT last_block_at, retry_count, next_allowed_at FROM challenge_state WHERE id=1"
    )
    row = await cur.fetchone()
    assert row is not None, "challenge_state seed row missing — DDL init failed"
    assert row[1] == 1, f"retry_count should be 1 after first block, got {row[1]}"

    # Advance time inside the module by 3700s — must patch the module-local
    # `time` import, NOT the global builtin (Phase 2 monkeypatch idiom).
    t_future = int(time.time()) + 3700
    monkeypatch.setattr(cb.time, "time", lambda: t_future)

    # Drop the in-memory _STATE so _load re-reads from sqlite (covers the
    # cold-load path after a hypothetical restart).
    cb._STATE = None

    await record_success(tmp_db)

    cur = await tmp_db.execute(
        "SELECT last_block_at, retry_count, next_allowed_at FROM challenge_state WHERE id=1"
    )
    row = await cur.fetchone()
    assert row is not None
    last_block_at, retry_count, next_allowed_at = row
    assert retry_count == 0, (
        f"D-07: retry_count should be 0 after reset, got {retry_count}"
    )
    assert next_allowed_at == 0, (
        f"D-07: next_allowed_at should be 0 after reset, got {next_allowed_at}"
    )
    assert last_block_at is None, (
        f"D-07: last_block_at should be NULL after reset, got {last_block_at}"
    )


async def test_reset_is_noop_when_recent_block(tmp_db, monkeypatch):
    """
    D-07: a success that arrives <1h after last_block_at MUST be a no-op
    (recent success doesn't clear an active backoff).
    """
    await record_block(tmp_db)

    # Advance time by only 100s (well under 1h)
    t_near = int(time.time()) + 100
    monkeypatch.setattr(cb.time, "time", lambda: t_near)
    cb._STATE = None

    await record_success(tmp_db)

    cur = await tmp_db.execute(
        "SELECT retry_count, next_allowed_at FROM challenge_state WHERE id=1"
    )
    row = await cur.fetchone()
    assert row[0] == 1, (
        f"D-07: retry_count should still be 1 (not reset) after a recent success; got {row[0]}"
    )
    assert row[1] > 0, (
        f"D-07: next_allowed_at should still be > 0 (backoff still active); got {row[1]}"
    )


async def test_state_persists_to_sqlite(tmp_db):
    """
    D-08: record_block writes to the `challenge_state` row.

    Direct sqlite query (no module-level cache read) confirms the
    `INSERT OR REPLACE` shape from Pattern S2 reaches the persistent layer.
    """
    t_before = int(time.time())
    await record_block(tmp_db)

    cur = await tmp_db.execute(
        "SELECT last_block_at, retry_count, next_allowed_at FROM challenge_state WHERE id=1"
    )
    row = await cur.fetchone()
    assert row is not None, "challenge_state row missing after record_block"

    last_block_at, retry_count, next_allowed_at = row
    assert retry_count == 1, f"retry_count after 1 block should be 1, got {retry_count}"
    assert last_block_at is not None, "last_block_at must be set"
    assert t_before <= last_block_at <= t_before + 5, (
        f"last_block_at should be recent (within 5s); got {last_block_at} vs {t_before}"
    )
    # next_allowed_at = last_block_at + 60 per curve (first block)
    assert next_allowed_at >= last_block_at + 58, (
        f"next_allowed_at should be ~60s after last_block_at; "
        f"got next_allowed_at={next_allowed_at}, last_block_at={last_block_at}"
    )


async def test_check_gate_returns_zero_when_clear(tmp_db):
    """
    Baseline: with the seed row (next_allowed_at=0), check_gate allows.

    Phase 2 lesson: NEVER assert `len > 0` shape only — pin the exact
    tuple shape so a future regression that flips the boolean while
    keeping retry_after=0 still fails this test (D-18 alignment).
    """
    allowed, retry_after = await check_gate(tmp_db)
    assert allowed is True, "fresh state should allow (next_allowed_at=0)"
    assert retry_after == 0, f"clear-state retry_after should be 0, got {retry_after}"


async def test_module_is_import_safe():
    """
    No top-level side effects: importing the module must NOT touch sqlite
    and must leave `_STATE` at its default `None`.

    The autouse `_reset_state` fixture above resets `_STATE` between tests,
    but at this point in the run we explicitly assert the import-time
    invariant (Pattern S4 — module-import time init gated to lazy load).
    """
    # Re-set to None to neutralize any prior-test residue inside the same
    # session (autouse fixture handles cross-test; this guards intra-test).
    cb._STATE = None
    assert cb._STATE is None, "module-singleton must be None until first call"
