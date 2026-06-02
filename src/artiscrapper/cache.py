"""
aiosqlite WAL cache — DDL, PRAGMAS, key hashing, gzip BLOBs, lazy TTL, hourly prune.
Pattern 2 from 02-RESEARCH.md (lines 427-551) — implemented verbatim.
CACHE-01: WAL schema. CACHE-02: gzip BLOB. CACHE-03: sha256 key. CACHE-04: lazy TTL.
T-02-01-02: Parameterized ? placeholders everywhere — no string interpolation in SQL.
"""

import asyncio
import gzip
import hashlib
import json
import re
import time
import unicodedata

import aiosqlite

PRAGMAS = [
    "PRAGMA journal_mode=WAL",  # concurrent reads while writing
    "PRAGMA synchronous=NORMAL",  # safe + ~2x faster than FULL
    "PRAGMA temp_store=MEMORY",
    "PRAGMA mmap_size=268435456",  # 256 MB mmap
    "PRAGMA cache_size=-32000",  # 32 MB page cache
    "PRAGMA wal_autocheckpoint=1000",  # default: 1000 pages = ~4 MB
    "PRAGMA busy_timeout=5000",  # wait 5s on contention
    "PRAGMA foreign_keys=ON",
]

_DDL = """
CREATE TABLE IF NOT EXISTS query_cache (
    cache_key       TEXT PRIMARY KEY,        -- sha256(query_norm).hexdigest()
    query           TEXT NOT NULL,           -- original query (forensics)
    query_norm      TEXT NOT NULL,           -- lowercase, trimmed, collapsed-ws
    response_json   TEXT NOT NULL,           -- full JSON response (without raw_serp_html)
    raw_serp_html_a BLOB,                    -- gzipped HTML of SERP A (q alone)
    raw_serp_html_b BLOB,                    -- gzipped HTML of SERP B (q +mercadolibre)
    created_at      INTEGER NOT NULL,        -- unix epoch
    expires_at      INTEGER NOT NULL,        -- unix epoch (created_at + 86400)
    bytes_total     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_cache_expires_at ON query_cache(expires_at);
CREATE INDEX IF NOT EXISTS ix_cache_created_at ON query_cache(created_at);
"""


async def init_schema(cache: aiosqlite.Connection) -> None:
    """Create the query_cache table and indexes if they don't exist."""
    await cache.executescript(_DDL)
    await cache.commit()


def normalize_query(query: str) -> str:
    """Normalize query for cache key: lowercase, NFKD, collapse whitespace, strip punctuation."""
    q = query.lower().strip()
    q = unicodedata.normalize("NFKD", q)
    q = re.sub(r"\s+", " ", q)
    # Strip accessory punctuation but keep alphanumeric + spaces
    q = re.sub(r"[^\w\s]", "", q)
    return q.strip()


def make_cache_key(query: str) -> str:
    """Cache key = sha256(normalize_query(query)).hexdigest() (CACHE-03)."""
    return hashlib.sha256(normalize_query(query).encode()).hexdigest()


async def get_cached(cache: aiosqlite.Connection, cache_key: str) -> dict | None:
    """
    Lazy TTL read: treat expired rows as misses (CACHE-04).
    NEVER DELETE in the hot path — let prune_loop sweep.
    Parameterized ? placeholder used (T-02-01-02).
    """
    row = await (
        await cache.execute(
            "SELECT response_json, expires_at FROM query_cache WHERE cache_key=?", (cache_key,)
        )
    ).fetchone()
    if row is None:
        return None
    response_json, expires_at = row
    if expires_at < int(time.time()):
        return None  # stale; let prune_loop sweep it
    return json.loads(response_json)


async def set_cached(
    cache: aiosqlite.Connection,
    cache_key: str,
    query: str,
    query_norm: str,
    response: dict,
    html_a: str,
    html_b: str,
    ttl_s: int = 86400,
) -> None:
    """
    Write response + gzipped SERP HTMLs to cache (CACHE-02).
    Parameterized ? placeholders everywhere (T-02-01-02).
    """
    now = int(time.time())
    blob_a = gzip.compress(html_a.encode("utf-8"), compresslevel=6)
    blob_b = gzip.compress(html_b.encode("utf-8"), compresslevel=6)
    resp_json = json.dumps(response, ensure_ascii=False)
    bytes_total = len(blob_a) + len(blob_b) + len(resp_json.encode())
    await cache.execute(
        """
        INSERT OR REPLACE INTO query_cache
            (cache_key, query, query_norm, response_json,
             raw_serp_html_a, raw_serp_html_b,
             created_at, expires_at, bytes_total)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cache_key, query, query_norm, resp_json, blob_a, blob_b, now, now + ttl_s, bytes_total),
    )
    await cache.commit()


async def prune_loop(cache: aiosqlite.Connection) -> None:
    """
    Hourly DELETE expired rows + size cap + nightly WAL checkpoint (CACHE-04).
    Runs as asyncio background task in lifespan.
    """
    while True:
        await asyncio.sleep(3600)  # hourly
        now = int(time.time())
        await cache.execute("DELETE FROM query_cache WHERE expires_at < ?", (now,))
        await cache.commit()
        # Size cap: 2 GB total raw bytes
        cur = await cache.execute("SELECT SUM(bytes_total) FROM query_cache")
        total = (await cur.fetchone())[0] or 0
        if total > 2_000_000_000:
            await cache.execute("""
                DELETE FROM query_cache WHERE cache_key IN (
                    SELECT cache_key FROM query_cache
                    ORDER BY created_at ASC LIMIT 100
                )
            """)
            await cache.commit()
        # Nightly WAL checkpoint (TRUNCATE flushes WAL to main db file)
        if now % 86400 < 3600:
            await cache.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await cache.commit()
