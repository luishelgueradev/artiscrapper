"""
Cache integration tests — fully implemented (cache.py ships in Task 2).
CACHE-01: WAL schema. CACHE-02: gzip BLOB. CACHE-03: sha256 key. CACHE-04: lazy TTL.
Uses tmp_db fixture (real sqlite file for WAL mode support).
"""
import asyncio
import gzip
import time

import pytest

from src.artiscrapper.cache import (
    get_cached,
    make_cache_key,
    normalize_query,
    set_cached,
)


async def test_schema(tmp_db):
    """CACHE-01: DDL creates query_cache table with expected columns."""
    cur = await tmp_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='query_cache'"
    )
    row = await cur.fetchone()
    assert row is not None, "query_cache table does not exist"

    # Verify key columns exist
    cur = await tmp_db.execute("PRAGMA table_info(query_cache)")
    cols = {r[1] for r in await cur.fetchall()}
    assert "cache_key" in cols
    assert "raw_serp_html_a" in cols
    assert "raw_serp_html_b" in cols
    assert "response_json" in cols
    assert "expires_at" in cols
    assert "created_at" in cols


async def test_gzip_roundtrip(tmp_db):
    """CACHE-02: set_cached gzips raw_serp_html BLOBs; decompress back = original."""
    original_html_a = "<html><body>SERP A content</body></html>"
    original_html_b = "<html><body>SERP B content mercadolibre</body></html>"
    query = "filtro aceite ford"
    key = make_cache_key(query)
    norm = normalize_query(query)
    response = {"results": [], "metadata": {"cache_hit": False}}

    await set_cached(
        tmp_db, key, query, norm, response, original_html_a, original_html_b
    )

    # Read the raw BLOBs from sqlite to verify gzip compression
    cur = await tmp_db.execute(
        "SELECT raw_serp_html_a, raw_serp_html_b FROM query_cache WHERE cache_key=?",
        (key,)
    )
    row = await cur.fetchone()
    assert row is not None, "Row was not inserted"
    blob_a, blob_b = row

    # Verify gzip magic header
    assert blob_a[:2] == b"\x1f\x8b", "SERP A blob is not gzipped"
    assert blob_b[:2] == b"\x1f\x8b", "SERP B blob is not gzipped"

    # Decompress and verify roundtrip
    decompressed_a = gzip.decompress(blob_a).decode("utf-8")
    decompressed_b = gzip.decompress(blob_b).decode("utf-8")
    assert decompressed_a == original_html_a, "SERP A decompress mismatch"
    assert decompressed_b == original_html_b, "SERP B decompress mismatch"


async def test_cache_key_deterministic(tmp_db):
    """CACHE-03: Identical normalized queries produce the same sha256 key."""
    q1 = "Filtro Aceite Ford Focus"
    q2 = "filtro  aceite  ford  focus"  # extra spaces
    q3 = "filtro aceite ford focus "    # trailing space

    key1 = make_cache_key(q1)
    key2 = make_cache_key(q2)
    key3 = make_cache_key(q3)

    assert key1 == key2, f"Keys differ for normalized-identical queries: {key1} vs {key2}"
    assert key1 == key3, f"Keys differ for normalized-identical queries: {key1} vs {key3}"

    # Verify it's a 64-char hex string (sha256 output)
    assert len(key1) == 64, f"Key length should be 64 hex chars, got {len(key1)}"
    assert all(c in "0123456789abcdef" for c in key1), "Key is not hex"


async def test_lazy_ttl(tmp_db):
    """CACHE-04: get_cached returns None for expired row (lazy TTL — never DELETE in hot path)."""
    query = "termostato corsa"
    key = make_cache_key(query)
    norm = normalize_query(query)
    response = {"results": [{"url": "https://example.com"}], "metadata": {}}

    # Insert with 1 second TTL
    await set_cached(tmp_db, key, query, norm, response, "<html/>", "<html/>", ttl_s=1)

    # Verify it's accessible immediately
    cached = await get_cached(tmp_db, key)
    assert cached is not None, "Freshly inserted entry should be accessible"

    # Wait for TTL to expire
    await asyncio.sleep(2)

    # Now it should return None (lazy TTL)
    expired = await get_cached(tmp_db, key)
    assert expired is None, "Expired entry should return None (lazy TTL)"

    # Row should still be in DB (lazy — not deleted yet)
    cur = await tmp_db.execute(
        "SELECT cache_key FROM query_cache WHERE cache_key=?", (key,)
    )
    row = await cur.fetchone()
    assert row is not None, "Row should still be in DB (prune_loop handles deletion, not hot path)"
