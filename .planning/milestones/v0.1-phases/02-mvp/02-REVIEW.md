---
phase: 02-mvp
reviewed: 2026-06-02T00:00:00Z
depth: standard
files_reviewed: 22
files_reviewed_list:
  - .github/workflows/ci.yml
  - src/artiscrapper/__init__.py
  - src/artiscrapper/browser.py
  - src/artiscrapper/cache.py
  - src/artiscrapper/config.py
  - src/artiscrapper/freshness.py
  - src/artiscrapper/llm.py
  - src/artiscrapper/logging_setup.py
  - src/artiscrapper/main.py
  - src/artiscrapper/metrics.py
  - src/artiscrapper/models.py
  - src/artiscrapper/rate_limit.py
  - src/artiscrapper/search.py
  - src/artiscrapper/visit.py
  - tests/conftest.py
  - tests/test_cache.py
  - tests/test_e2e.py
  - tests/test_footguns.py
  - tests/test_health.py
  - tests/test_llm.py
  - tests/test_parser.py
  - tests/test_visit.py
findings:
  critical: 2
  warning: 5
  info: 4
  total: 11
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-06-02T00:00:00Z
**Depth:** standard
**Files Reviewed:** 22
**Status:** issues_found

## Summary

Reviewed the full Phase 2 MVP implementation: 14 source modules and 7 test files. D2/D6/D8 invariants are correctly enforced — the fallback cutoff is hard at 0.3, uvloop is absent, and `launch_persistent_context` does not appear. The LLM pipeline, cache, and rate limiter are structurally sound.

Two BLOCKER-level issues were found: (1) FRESH-02 (date-based freshness) is entirely dead because `assess_freshness` is always called with `extracted=None` and `verdict=None` from the pipeline — the only freshness signal that survives is FRESH-01 (MELI host check); (2) a resource leak in `health_deep` and `_recycle_browser_loop` where Chromium context/page objects are never closed on the exception path. Additionally, the VISIT-08 MELI guard uses a raw substring match that produces false positives for any domain containing `mercadolibre.` as an internal substring (e.g. `notmercadolibre.com`).

---

## Critical Issues

### CR-01: FRESH-02 date-based freshness is permanently dead code

**File:** `src/artiscrapper/main.py:372-378` and `src/artiscrapper/freshness.py:81-88`

**Issue:** `assess_freshness` is called with both `verdict=None` and `extracted=None` on every request. This silently disables two of the three freshness signal paths:

- **FRESH-02** (`extracted` date check, lines 82–88 of `freshness.py`): the `if extracted:` guard is always `False` → never executes.
- **live_marketplace verdict check** (line 91 of `freshness.py`): the `if verdict is not None` guard is always `False` → never executes.

Only **FRESH-01** (MELI host check) is reachable. The `date_modified` field extracted by `visit.py` and stored in `candidate` via `candidate.update(extracted)` is ignored by `assess_freshness` because the function reads from its `extracted` parameter, not from the `candidate` dict.

The developer comment at line 375 (`"verdict not stored per-candidate; freshness_signal is in candidate"`) acknowledges that `freshness_signal` lives in the candidate dict, but the function signature was never updated to read it from there. This means all non-MELI candidates will always return `fresh=None` regardless of their `date_modified` value.

**Fix:** Either pass `extracted` from the candidate dict, or rewrite the call site to extract the fields that are already present on the candidate:

```python
# main.py: pass the candidate's own date field as extracted
for candidate in survivors:
    extracted_for_freshness = (
        {"date_modified": candidate.get("date_modified")}
        if candidate.get("date_modified")
        else None
    )
    fresh_val = assess_freshness(
        candidate,
        verdict=None,
        extracted=extracted_for_freshness,
    )
    candidate["fresh"] = fresh_val
```

Or, preferably, have `assess_freshness` read `candidate.get("date_modified")` directly (and read `candidate.get("freshness_signal")` for the `live_marketplace` path), removing the `extracted` and `verdict` parameters from the hot path entirely.

---

### CR-02: Chromium context/page leaked on exception in `health_deep` and `_recycle_browser_loop`

**File:** `src/artiscrapper/main.py:196-208` (health_deep) and `src/artiscrapper/main.py:76-88` (_recycle_browser_loop)

**Issue:** In both locations, `ctx` and `page` are created in the `try` block but `page.close()` / `ctx.close()` are only called on the **success path**. If any line between `new_context()` and the success close raises, the context and page objects are orphaned inside the browser process.

In `health_deep`:
```python
ctx = await browser.new_context()
page = await ctx.new_page()
await asyncio.wait_for(
    page.goto("about:blank", ...),   # <-- if this raises
    timeout=5.0,
)
out["cloak"] = "ok_deep"
await page.close()   # never reached
await ctx.close()    # never reached
```

In `_recycle_browser_loop`, the same pattern: if `page.evaluate("1")` raises (the intended SIGSTOP detection path), `page.close()` and `ctx.close()` are skipped. The old browser is then closed (`browser.close()`), which should close its child contexts, but relying on browser teardown for context cleanup is fragile.

`health_deep` is called from cron/smoke tests, but each failure accumulates a leaked context in the live browser singleton.

**Fix:** Wrap both locations with `try/finally`:

```python
# health_deep
ctx = await browser.new_context()
try:
    page = await ctx.new_page()
    try:
        await asyncio.wait_for(
            page.goto("about:blank", wait_until="domcontentloaded"),
            timeout=5.0,
        )
        out["cloak"] = "ok_deep"
    finally:
        await page.close()
finally:
    await ctx.close()
```

The same `try/finally` pattern should be applied to the heartbeat block in `_recycle_browser_loop` (lines 76–88).

---

## Warnings

### WR-01: VISIT-08 MELI guard fires on false-positive domains

**File:** `src/artiscrapper/visit.py:330`

**Issue:** The guard uses a raw substring check: `"mercadolibre." in urlparse(url).netloc`. This silently drops any domain that happens to contain `mercadolibre.` as a substring. For example:

```python
# urlparse("https://notmercadolibre.com/foo").netloc = "notmercadolibre.com"
"mercadolibre." in "notmercadolibre.com"  # True — guard fires incorrectly
```

Domains such as `notmercadolibre.com`, `api.notmercadolibre.com.ar`, or any phishing-style domain ending in `mercadolibre.com.ar` would be silently skipped without a visit, causing them to appear in results without extracted price/availability data. The impact is correctness (skipped visits), not security (the guard direction is skip, not allow).

**Fix:** Check that `mercadolibre.` appears as a domain component boundary, not as an arbitrary substring:

```python
# visit.py, inside visit_one()
netloc = urlparse(url).netloc.lower()
if netloc == "mercadolibre.com.ar" or netloc.endswith(".mercadolibre.com.ar") \
        or netloc == "mercadolibre.com" or netloc.endswith(".mercadolibre.com"):
    candidate["flags"] = candidate.get("flags", []) + ["meli_skip"]
    return candidate
```

Alternatively, reuse the `MELI_HOSTS` frozenset already defined in `freshness.py` (or move it to a shared location) and apply the same `endswith` pattern used there.

---

### WR-02: Fire-and-forget `create_task` without a strong reference (cache write)

**File:** `src/artiscrapper/main.py:418`

**Issue:** `asyncio.create_task(_write_cache())` is called without storing the returned task object. CPython's GC may collect the task before it completes in low-memory conditions. The Python asyncio docs explicitly warn about this pattern.

**Fix:** Store the task or add it to a set:

```python
_bg_tasks: set[asyncio.Task] = set()

task = asyncio.create_task(_write_cache())
_bg_tasks.add(task)
task.add_done_callback(_bg_tasks.discard)
```

A module-level `_bg_tasks` set (or a set on `app.state`) prevents GC while the task is running.

---

### WR-03: `test_recycle_triggers` contains a tautological assertion that tests nothing

**File:** `tests/test_footguns.py:62`

**Issue:** The first assertion is `assert BROWSER_RECYCLE_AFTER >= BROWSER_RECYCLE_AFTER`, which is always `True` (a value is always `>=` itself). This assertion provides zero coverage of BROWSER-03 behaviour and would pass even if the recycle condition were removed from the codebase entirely. The subsequent assertions (lines 67–76) do test the threshold logic correctly, but the tautology on line 62 misleadingly implies a more thorough test.

**Fix:** Replace the tautological assertion with one that verifies the exact boundary condition:

```python
# Line 62 should be:
assert 200 >= BROWSER_RECYCLE_AFTER, (
    "Sanity: threshold constant must be <= 200 (change this if you change the default)"
)
```

Or simply remove line 62 and keep only the meaningful assertions on lines 67–76.

---

### WR-04: `test_health.py` creates a leaked temp file at module import time

**File:** `tests/test_health.py:18-21`

**Issue:** `tempfile.NamedTemporaryFile(suffix=".db", delete=False)` is called at module-level with `delete=False`. The file is never cleaned up — it persists in the OS temp directory across test runs indefinitely. Additionally, `os.environ["CACHE_DB_PATH"] = _tmp_db.name` is set unconditionally (not via `setdefault`) at module-level, meaning it overrides any value a caller may have set.

**Fix:** Use a `tmp_path`-based fixture or at minimum register an `atexit` cleanup. The env var override should use `os.environ.setdefault` consistent with the `LLM_ROUTER_BEARER_TOKEN` line directly above it.

```python
# Use setdefault for consistency
os.environ.setdefault("CACHE_DB_PATH", _tmp_db.name)
```

For the temp file leak, register cleanup:

```python
import atexit
atexit.register(lambda: os.unlink(_tmp_db.name) if os.path.exists(_tmp_db.name) else None)
```

---

### WR-05: `classify_response` calls `HTMLParser` and parses full body for every successful visit response

**File:** `src/artiscrapper/visit.py:97-101`

**Issue:** `classify_response` builds an `HTMLParser(response.text)` on every live response to check the `<title>` and `<h1>` for dead-page markers. This same HTML is then passed to `extract_product(resp.text)` (line 374 of `visit.py`), which calls `HTMLParser(html)` again — parsing the same document twice. The double parse is wasteful but also creates a subtle inconsistency: if the document is large or malformed, the two parsers may produce different results.

**Fix:** Parse once and thread the tree:

```python
async def visit_one(candidate: dict) -> dict:
    ...
    html = resp.text
    tree = HTMLParser(html)
    outcome = classify_response_from_tree(resp, tree)
    ...
    extracted = extract_product_from_tree(tree)
```

This requires refactoring `classify_response` and `extract_product` to accept an already-parsed tree, but aligns with the existing `extract_jsonld_product(tree)` / `extract_og_product(tree)` signatures.

---

## Info

### IN-01: System prompt says `reason: máximo 80 caracteres` but `LLMVerdict.reason` allows 140

**File:** `src/artiscrapper/llm.py:73` (prompt) and `src/artiscrapper/llm.py:32` (model)

**Issue:** The system prompt instructs the LLM to keep `reason` under 80 characters, but the Pydantic model validates `reason` with `max_length=140`. A response with a 100-character reason would pass model validation but violate the prompt constraint. The discrepancy may cause unexpected long reasons in logs.

**Fix:** Align the two constants: either set `reason: str = Field(max_length=80)` or update the prompt to reflect 140 characters.

---

### IN-02: `parse_serp` carousel loop calls `_extract_carousel(n)` twice per node

**File:** `src/artiscrapper/search.py:185`

**Issue:** The list comprehension `[_extract_carousel(n) for n in nodes if _extract_carousel(n)]` calls `_extract_carousel` once in the filter predicate and again to produce the value. Each call independently walks the node's CSS selectors. Since `_extract_carousel` is pure this is not a correctness bug, but it doubles the work for carousel nodes.

**Fix:**
```python
carousel_results = [r for n in nodes if (r := _extract_carousel(n))]
```

---

### IN-03: `reason` field of `LLMVerdict` is logged indirectly via `fallback()` prefix `llm_fail:`

**File:** `src/artiscrapper/llm.py:44` and `src/artiscrapper/llm.py:227`

**Issue:** `LLMVerdict.fallback()` sets `reason="llm_fail:{reason}"` and `curate_candidates` detects fallback verdicts by checking `verdict.reason.startswith("llm_fail:")`. This couples two distinct concerns (the fallback detection heuristic and the reason string format) through a fragile string-prefix convention. If `fallback()` reason format ever changes, the detection silently breaks.

**Fix:** Add an explicit `is_fallback: bool = False` field to `LLMVerdict`, set it `True` in `fallback()`, and use `verdict.is_fallback` in `curate_candidates` instead of string inspection.

---

### IN-04: CI uvloop grep command passes silently when input files are missing

**File:** `.github/workflows/ci.yml:45`

**Issue:** The command `grep -rE 'uvloop' pyproject.toml uv.lock && ... || echo "OK: uvloop absent"` exits 0 (success) not only when uvloop is absent but also when `grep` exits with code 2 (file-not-found error). If `uv.lock` were missing or renamed, the step would report `"OK: uvloop absent"` even though the check was not actually performed.

In practice, the `uv sync --locked` step that precedes this would fail if `uv.lock` is absent, so the risk is low. Still, the logic could be hardened:

```bash
set -e
if grep -rE 'uvloop' pyproject.toml uv.lock 2>/dev/null; then
  echo "FAIL: uvloop found — D6 foot-gun!" && exit 1
fi
echo "OK: uvloop absent"
```

---

_Reviewed: 2026-06-02T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
