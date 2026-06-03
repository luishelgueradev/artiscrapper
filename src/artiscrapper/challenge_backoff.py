"""
ChallengeBackoff — Google challenge-detection backoff state machine.

Phase 3 — Plan 03-02 — D-05/D-06/D-07/D-08/D-09.

Pattern S1 (module-singleton + asyncio.Lock + double-checked-load):
  Mirrors `src/artiscrapper/llm.py:93-141` (`_RESOLVED_MODEL` + `_RESOLVE_LOCK`
  + `resolve_model`). The in-memory `_STATE` is the hot-path cache; sqlite
  is the persistence layer for restart survival.

Pattern S2 (sqlite UPSERT with parameterized placeholders):
  Mirrors `src/artiscrapper/cache.py:106-116` (`INSERT OR REPLACE
  ... VALUES (?, ...)` + immediate `commit()`). NEVER string interpolation
  in SQL — Phase 2 lesson T-02-01-02.

Public surface:
  - check_gate(cache) → (allowed, retry_after_s). Called BEFORE every
    Google fetch in `/search`. Read-only on the hot path (no lock).
  - record_block(cache) → no-op return. Called when `_detect_block`
    fires. Acquires `_LOCK`, increments retry_count, persists.
  - record_success(cache) → no-op return. Called after a successful
    Google fetch. Resets retry_count to 0 IFF the success comes ≥1h
    after `last_block_at` (D-07 trigger), else no-op.

D-06 ROADMAP-lock (NOT thread-able through settings — Pitfall 6):
  _BASE_S = 60
  _BACKOFF_CAP_S = 3600
  _RESET_AFTER_S = 3600

  Backoff curve:  wait_s = min(_BASE_S * (2 ** (retry_count - 1)),
                               _BACKOFF_CAP_S)
  Sequence:       60, 120, 240, 480, 960, 1920, 3600, 3600, …

D-08 persistence: single-row `challenge_state` table created by
`cache._DDL`. `CHECK(id=1)` constraint guarantees the single row;
`INSERT OR IGNORE` seeds it idempotently at init_schema.

D-19 (Phase 2 memory `feedback_empirical_retest_after_default_changes`):
  The constants are underscore-prefixed so they're private but
  introspectable. `main.py` lifespan reads them and emits a
  `challenge_backoff_init` log line declaring the running values, so
  `docker compose logs | grep challenge_backoff_init` empirically
  verifies the values reached the hot path.
"""

import asyncio
import time
from dataclasses import dataclass

import aiosqlite

# ── D-06 / D-07 constants (ROADMAP-locked — never settings-threaded) ──
_BASE_S = 60
_BACKOFF_CAP_S = 3600
_RESET_AFTER_S = 3600


@dataclass
class _State:
    """In-memory snapshot of the `challenge_state` sqlite row."""

    last_block_at: int | None
    retry_count: int
    next_allowed_at: int


# Module-level singleton — Pattern S1.
# Lazy-loaded on first call (NO top-level sqlite touch — module import
# is side-effect-free). Resets via test fixtures by re-assigning to None.
_STATE: _State | None = None
_LOCK = asyncio.Lock()


async def _load(cache: aiosqlite.Connection) -> _State:
    """
    Double-checked-load: return cached `_STATE` outside the lock if set,
    else acquire the lock, re-check, then cold-load from sqlite.

    Mirrors `llm.py::resolve_model` exactly. The double check prevents a
    race where two concurrent first-callers both perform the sqlite read.
    """
    global _STATE
    if _STATE is not None:
        return _STATE
    async with _LOCK:
        if _STATE is not None:
            return _STATE
        cur = await cache.execute(
            "SELECT last_block_at, retry_count, next_allowed_at "
            "FROM challenge_state WHERE id=1"
        )
        row = await cur.fetchone()
        if row is None:
            # Should never happen — `init_schema` seeds via INSERT OR
            # IGNORE. Defensive fallback so an empty table doesn't
            # crash check_gate on the hot path.
            _STATE = _State(last_block_at=None, retry_count=0, next_allowed_at=0)
        else:
            _STATE = _State(
                last_block_at=row[0],
                retry_count=row[1],
                next_allowed_at=row[2],
            )
        return _STATE


async def _persist(cache: aiosqlite.Connection) -> None:
    """
    Write `_STATE` to sqlite. Caller MUST hold `_LOCK`.

    Pattern S2: INSERT OR REPLACE with parameterized `?` placeholders +
    immediate `commit()`. Phase 2 lesson T-02-01-02 — never string
    interpolation in SQL.
    """
    assert _STATE is not None, "_persist called before _load — programmer error"
    now = int(time.time())
    await cache.execute(
        "INSERT OR REPLACE INTO challenge_state "
        "(id, last_block_at, retry_count, next_allowed_at, updated_at) "
        "VALUES (1, ?, ?, ?, ?)",
        (
            _STATE.last_block_at,
            _STATE.retry_count,
            _STATE.next_allowed_at,
            now,
        ),
    )
    await cache.commit()


async def check_gate(cache: aiosqlite.Connection) -> tuple[bool, int]:
    """
    Returns `(allowed, retry_after_s)` — gate the next Google fetch.

    Called BEFORE every Google round-trip in `/search` (D-09). Read-
    only on the hot path — no lock acquisition, no sqlite write.

    `allowed=False, retry_after > 0`  → caller returns 503 +
        `Retry-After: retry_after` header (handled in main.py).
    `allowed=True, retry_after=0`     → caller proceeds with fetch.
    """
    state = await _load(cache)
    now = int(time.time())
    if state.next_allowed_at > now:
        return False, state.next_allowed_at - now
    return True, 0


async def record_block(cache: aiosqlite.Connection) -> None:
    """
    Persist a block event. Called from `/search` when `_detect_block`
    returns a non-None reason (D-09).

    Acquires `_LOCK` for the read-modify-write cycle so concurrent
    requests that ALL detect a block don't double-increment
    `retry_count` (D-06 curve assumes monotonic count).

    Curve (D-06):  wait_s = min(_BASE_S * (2 ** (retry_count - 1)),
                                _BACKOFF_CAP_S)
    """
    async with _LOCK:
        # We hold the lock — bypass the public _load (which would
        # re-acquire). Read or lazy-init `_STATE` directly while we
        # already own _LOCK.
        global _STATE
        if _STATE is None:
            cur = await cache.execute(
                "SELECT last_block_at, retry_count, next_allowed_at "
                "FROM challenge_state WHERE id=1"
            )
            row = await cur.fetchone()
            if row is None:
                _STATE = _State(
                    last_block_at=None, retry_count=0, next_allowed_at=0
                )
            else:
                _STATE = _State(
                    last_block_at=row[0],
                    retry_count=row[1],
                    next_allowed_at=row[2],
                )

        now = int(time.time())
        # WR-01: snapshot the pre-mutation state so we can revert if
        # _persist raises (sqlite full / locked / IO error). Without the
        # revert, the in-memory _STATE would advance (retry_count++,
        # next_allowed_at moved forward) while the durable row stays
        # behind — after a container restart the gate would re-open
        # 60s × 2^N too early. The persist failure still propagates to
        # the caller (which is now wrapped by WR-02 in main.py).
        prev = (_STATE.retry_count, _STATE.last_block_at, _STATE.next_allowed_at)
        _STATE.retry_count += 1
        wait_s = min(_BASE_S * (2 ** (_STATE.retry_count - 1)), _BACKOFF_CAP_S)
        _STATE.last_block_at = now
        _STATE.next_allowed_at = now + wait_s
        try:
            await _persist(cache)
        except Exception:
            (
                _STATE.retry_count,
                _STATE.last_block_at,
                _STATE.next_allowed_at,
            ) = prev
            raise


async def record_success(cache: aiosqlite.Connection) -> None:
    """
    Persist a successful Google fetch. Called on the /search success
    path (D-07).

    Behavior:
      - If `last_block_at` is None (never blocked) → no-op.
      - If `now - last_block_at >= _RESET_AFTER_S` (≥1h since last
        block) → reset retry_count=0, next_allowed_at=0,
        last_block_at=None, then persist.
      - Otherwise (recent success during active backoff) → no-op.
        A recent success does NOT clear an active backoff — the gate
        stays armed until the cool-off window elapses.
    """
    async with _LOCK:
        global _STATE
        if _STATE is None:
            cur = await cache.execute(
                "SELECT last_block_at, retry_count, next_allowed_at "
                "FROM challenge_state WHERE id=1"
            )
            row = await cur.fetchone()
            if row is None:
                _STATE = _State(
                    last_block_at=None, retry_count=0, next_allowed_at=0
                )
            else:
                _STATE = _State(
                    last_block_at=row[0],
                    retry_count=row[1],
                    next_allowed_at=row[2],
                )

        if _STATE.last_block_at is None:
            # Never blocked — nothing to reset. Avoids a spurious
            # sqlite write on every successful /search request.
            return

        now = int(time.time())
        if now - _STATE.last_block_at >= _RESET_AFTER_S:
            _STATE.retry_count = 0
            _STATE.next_allowed_at = 0
            _STATE.last_block_at = None
            await _persist(cache)
