# Phase 3 — Robustness — Security Audit

**Phase:** 03-robustness (plans 03-01 + 03-02)
**ASVS Level:** 1
**Block-on:** HIGH
**Audit date:** 2026-06-03
**Verdict:** SECURED (21/21 threats resolved; 0 OPEN; 0 unregistered flags)

---

## Threat Verification — Plan 03-01 (11 threats)

| Threat ID | Category | Severity | Disposition | Status | Evidence |
|-----------|----------|----------|-------------|--------|----------|
| T-03-01-01 | Spoofing | HIGH | mitigate | VERIFIED | `src/artiscrapper/auth.py:50-79` — `verify_api_key()` raises `HTTPException(401, headers={"WWW-Authenticate": "ApiKey"})` for missing/unknown key (uses `hmac.compare_digest` per CR-01). Wired on `/search` via `_api_key: str = Depends(verify_api_key)` at `src/artiscrapper/main.py:361`. Also wired on `/health/deep` at `main.py:292` (CR-03 — hardening beyond plan). |
| T-03-01-02 | Tampering / DoS | HIGH | mitigate | VERIFIED | Stacked `@limiter.limit("60/minute")` + `@limiter.limit("10000/day")` at `src/artiscrapper/main.py:355-356`. `Limiter(key_func=get_api_key, headers_enabled=True)` at `main.py:240`; exception handler registered `main.py:242`. `Response` param at `main.py:359` ensures slowapi can inject `X-RateLimit-*` + `Retry-After`. |
| T-03-01-03 | Info Disclosure | MEDIUM | accept | ACCEPTED | See "Accepted Risks" log below — `/metrics` mounted via `make_asgi_app()` at `src/artiscrapper/main.py:257`; pinned by `tests/test_footguns.py:130-148` (`test_metrics_endpoint_unprotected_by_design`). Default Python-VM collectors unregistered at `src/artiscrapper/metrics.py:39-43`. |
| T-03-01-04 | Info Disclosure | HIGH | mitigate | VERIFIED | `src/artiscrapper/logging_setup.py:129-162` — `_init_sentry()` returns early when `settings.SENTRY_DSN` empty (D-14, line 139-140); when set, calls `sentry_sdk.init(..., send_default_pii=False)` line 156. CR-02: init wrapped in try/except so a malformed DSN cannot crash boot. Module-import-time invocation at `logging_setup.py:168`. |
| T-03-01-05 | Info Disclosure | MEDIUM | mitigate | VERIFIED | `src/artiscrapper/logging_setup.py:63-69` — `set_tag("correlation_id", cid)` wrapped in `try: ... except (AttributeError, RuntimeError):`. WR-05 hardening: narrowed catch + one-shot `_sentry_tag_warned` flag at `logging_setup.py:21` so SDK drift surfaces once in structured logs instead of being permanently silenced. |
| T-03-01-06 | Tampering | MEDIUM | mitigate | VERIFIED | `src/artiscrapper/metrics.py:106-117` — `_host_for_metric()` uses `tldextract` to normalize host to `domain.suffix` (TLD+1) with `"unknown"` fallback for edge cases. Pre-seeding of bounded `reason` labels at `metrics.py:145-163`; `host` intentionally NOT pre-seeded (unbounded). |
| T-03-01-07 | Tampering | MEDIUM | mitigate | VERIFIED | `pyproject.toml:22-24` pins `prometheus-client==0.25.0`, `sentry-sdk==2.61.1`, `slowapi==0.1.9`. `uv.lock` foot-gun verified: `grep -c uvloop uv.lock` returns **0**. `tests/test_footguns.py:112-127` (`test_sentry_does_not_pull_uvloop`) re-asserts D-6 against sentry-sdk transitive deps. |
| T-03-01-08 | Info Disclosure / Repudiation | MEDIUM | mitigate | VERIFIED | `src/artiscrapper/logging_setup.py:51-69` — `if cid:` branch sets event-dict `correlation_id` AND calls `sentry_sdk.get_current_scope().set_tag("correlation_id", cid)` (line 64). Wrapped per T-03-01-05 mitigation. Joinable cross-request tag confirmed. |
| T-03-01-09 | Repudiation | LOW | accept | ACCEPTED | See "Accepted Risks" log — per-key audit telemetry deferred to Phase 5 (MULTI-03). `auth.py` logs only `api_keys_loaded.count` aggregate (OBS-05). |
| T-03-01-10 | EoP | LOW | accept | ACCEPTED | See "Accepted Risks" log — slowapi 429 fires before `verify_api_key` 401 (slowapi 0.1.9 contract; alternative would require custom middleware breaking slowapi). Information-leakage-free: 401 returned until anonymous bucket exhausted. |
| T-03-01-11 | Info Disclosure | MEDIUM | mitigate | VERIFIED | `src/artiscrapper/logging_setup.py:100-102` — `SAFE_CANDIDATE_FIELDS = frozenset({"url_hash", "host", "has_price", "freshness_signal", "confidence"})` unchanged. Lifespan log lines at `src/artiscrapper/main.py:156-188` log only `count`/`rate_per_min`/`rate_per_day`/`traces_sample_rate`/`per_min`/`per_day`/`base_s`/`cap_s`/`reset_after_s` — never API_KEYS values, never SENTRY_DSN, never per-key data. `auth.py:97-101` confirms only count is logged. |

---

## Threat Verification — Plan 03-02 (10 threats)

| Threat ID | Category | Severity | Disposition | Status | Evidence |
|-----------|----------|----------|-------------|--------|----------|
| T-03-02-01 | DoS | HIGH | mitigate | VERIFIED | `src/artiscrapper/challenge_backoff.py:53-55` — `_BASE_S=60`, `_BACKOFF_CAP_S=3600`, `_RESET_AFTER_S=3600` (module-level, NOT settings-threaded — D-06 / Pitfall 6). Curve `min(_BASE_S * 2**(retry_count-1), _BACKOFF_CAP_S)` at `challenge_backoff.py:193`. `_LOCK = asyncio.Lock()` at line 71 serializes `record_block`. D-07 reset trigger at `challenge_backoff.py:246-250`. |
| T-03-02-02 | Tampering / Loss of Integrity | MEDIUM | mitigate | VERIFIED | `src/artiscrapper/cache.py:49-58` — `CREATE TABLE challenge_state (id INTEGER PRIMARY KEY CHECK (id = 1), ...)` + `INSERT OR IGNORE INTO challenge_state ... VALUES (1, ...)` idempotent seed. Parameterized `?` placeholders for the UPSERT at `challenge_backoff.py:117-127` (Pattern S2 — T-02-01-02 from Phase 2 honored). |
| T-03-02-03 | DoS (silent) | MEDIUM | mitigate | VERIFIED | `src/artiscrapper/main.py:429-452` — gate-denied branch returns `Response(status_code=503, ..., headers={"Retry-After": str(retry_after)})`. NOT a silent timeout. Used `Response` (not `HTTPException`) per 03-RESEARCH.md §D3 to preserve `SearchResponse` pydantic shape. |
| T-03-02-04 | DoS | HIGH | mitigate | VERIFIED | `src/artiscrapper/main.py:550-582` — `router_health_check` failure path: `llm_degraded = True`, falls back to heuristic `[c for c in all_candidates if c.get("has_price")]`. Also covers post-curate fallback at lines 566-571 (`llm_degraded and not survivors` → heuristic). Pinned by `tests/integration/test_degraded_mode.py` (28/50 survivors measured, ≥5 bar). |
| T-03-02-05 | Tampering | MEDIUM | mitigate | VERIFIED | `tests/integration/test_catalog_extraction.py` — `test_catalog_price_extraction_rate_above_85_percent` sweeps all 10 Phase 1 catalog fixtures with per-fixture `(filename, has_price, price)` details (D-18). 10/10 = 100% measured (acceptance ≥85%). |
| T-03-02-06 | Info Disclosure | MEDIUM | mitigate | VERIFIED | `src/artiscrapper/main.py:436` — `log.warning("challenge_backoff_active", retry_after=retry_after)` carries ONLY the numeric retry_after. Sorry-page HTML never logged. Synthetic fixture at `tests/fixtures/serp/blocks/sorry.html` (D-20 stand-in, no real Google content). |
| T-03-02-07 | Spoofing | LOW | accept | ACCEPTED | See "Accepted Risks" log — synthetic sorry.html. Future Phase 4 telemetry `block_detected_total{reason}` (already wired by Plan 03-01 — `src/artiscrapper/metrics.py:57-61` + `inc_block_detected` at `main.py:490`) will surface real production marker reasons. |
| T-03-02-08 | Default Shadowing | MEDIUM | mitigate | VERIFIED | `src/artiscrapper/challenge_backoff.py:53-55` — constants hardcoded at module level (NOT in `config.py` Settings). Lifespan `challenge_backoff_init` log line at `src/artiscrapper/main.py:183-188` reads `challenge_backoff._BASE_S/_BACKOFF_CAP_S/_RESET_AFTER_S` directly so a misconfiguration would surface in container logs (D-19). |
| T-03-02-09 | Race Condition | MEDIUM | mitigate | VERIFIED | `src/artiscrapper/challenge_backoff.py:71` — `_LOCK = asyncio.Lock()`. `record_block` acquires lock at line 161 (`async with _LOCK`) and reads/writes `_STATE` directly inside (bypasses `_load` to avoid lock re-entry — see deviation #3 in 03-02-SUMMARY.md). `record_success` follows the same pattern at line 221. WR-01 hardening: snapshot/revert at lines 191-204 ensures in-memory state and durable row stay aligned on persist failure. |
| T-03-02-10 | Repudiation | LOW | accept | ACCEPTED | See "Accepted Risks" log — `block_detected_total{reason}` Counter wired (Plan 03-01), correlation_id propagates to 503 (via CorrelationIdMiddleware at `main.py:261`). Per-key block attribution deferred to Phase 5. |

---

## Accepted Risks Log

The following threats are explicitly accepted in the threat register with `disposition=accept`. They are NOT bugs; they are recorded business / scope decisions.

### AR-01 — T-03-01-03 — `/metrics` exposed without auth on the same port as `/search`

- **Rationale:** D-10 design decision; the container runs on an internal docker network. Exposing `/metrics` publicly requires a reverse proxy with IP allowlist (deferred to Phase 4 in CONTEXT.md).
- **Mitigation present:** Default Python-VM collectors (`GC_COLLECTOR`, `PLATFORM_COLLECTOR`, `PROCESS_COLLECTOR`) are unregistered (`src/artiscrapper/metrics.py:39-43`) so the surface contains only `artiscrapper_*` series. No PII; no scraped content; only counts + histogram buckets.
- **Re-evaluation trigger:** Public exposure of the container port to the internet.

### AR-02 — T-03-01-09 — No per-API-key audit trail on `/search`

- **Rationale:** Single-tenant deploy (Sánchez Repuestos); per-key billing/audit telemetry is a Phase 5 multi-tenancy feature (MULTI-03).
- **Mitigation present:** Per-request `correlation_id` propagates through structlog and Sentry tags (T-03-01-08). API_KEYS aggregate count is logged at boot via OBS-05-aligned `api_keys_loaded` event.
- **Re-evaluation trigger:** Onboarding a second consumer.

### AR-03 — T-03-01-10 — Unauthenticated requests consume the `anonymous` rate-limit bucket

- **Rationale:** slowapi 0.1.9's middleware ordering puts the rate limit before FastAPI Depends. Inverting this requires custom middleware that breaks slowapi's contract.
- **Mitigation present:** The information leak is absent — failed-auth requests get 401 (not 429) until the anonymous bucket's 60/min quota is consumed. Brute-force throughput therefore capped at 60/min from any source.
- **Re-evaluation trigger:** Threat model upgrades to ASVS Level 2+ (would require formal credential-stuffing defense).

### AR-04 — T-03-02-07 — Synthetic `sorry.html` fixture may diverge from real Google sorry pages

- **Rationale:** Phase 1 SPIKE did not capture a real `/sorry/` page (verified — only 10 standard SERP fixtures exist). Per D-20 the stand-in was authored to match `browser._detect_block()` markers.
- **Mitigation transferred (NOT pure accept):** The `artiscrapper_block_detected_total{reason}` Counter (Plan 03-01, `src/artiscrapper/metrics.py:57-61` + `main.py:490`) will surface the actual marker reasons hitting production. If real sorry-page HTML rotates such that `_detect_block` stops firing, the counter will go quiet — actionable signal even without a real captured fixture. Future capture/refresh is a Phase 4 telemetry item.
- **Re-evaluation trigger:** `block_detected_total` drops to zero while consumers report stalled searches (would indicate marker drift).

### AR-05 — T-03-02-10 — No per-key block-detection audit trail

- **Rationale:** Same as AR-02 — single-tenant deploy; per-key attribution is Phase 5 work.
- **Mitigation present:** `block_detected_total{reason}` Prometheus Counter + `challenge_state.updated_at` forensics timestamp + `correlation_id` propagation cover the single-client case.
- **Re-evaluation trigger:** Same as AR-02.

---

## Unregistered Threat Flags

Neither `03-01-SUMMARY.md` nor `03-02-SUMMARY.md` contains a `## Threat Flags` section. `03-02-SUMMARY.md:158-171` includes a `## Threat-Model Acceptance` block enumerating every T-03-02-* row — all 10 map directly to the threat register. No new attack surface was introduced beyond the 21 declared threats.

**Cross-check — features actually implemented vs threats covered:**

| Implemented surface | Mapped threat(s) |
|---------------------|-------------------|
| `verify_api_key` on `/search` and `/health/deep` (CR-03 also on `/health/deep`) | T-03-01-01 |
| Stacked slowapi rate limit on `/search` | T-03-01-02 |
| `/metrics` ASGI sub-app | T-03-01-03 (accept) |
| Sentry SDK gated init | T-03-01-04, T-03-01-05, T-03-01-08 |
| Counter cardinality TLD+1 normalization | T-03-01-06 |
| Dep pins + uvloop foot-gun | T-03-01-07 |
| OBS-05 allow-list preserved + new lifespan log lines | T-03-01-11 |
| ChallengeBackoff state machine + persistence | T-03-02-01, T-03-02-02, T-03-02-09 |
| 503 + Retry-After on gate denial | T-03-02-03 |
| Degraded mode (heuristic + price-in-card) | T-03-02-04 |
| Catalog extraction integration test | T-03-02-05 |
| `challenge_backoff_active` log carries only `retry_after` | T-03-02-06 |
| Synthetic sorry.html fixture | T-03-02-07 (accept/transfer) |
| `challenge_backoff_init` D-19 log line for constants | T-03-02-08 |
| `block_detected_total` Counter + correlation_id | T-03-02-10 (accept) |

No unregistered surface.

---

## Auditor Notes — Hardening beyond plan

These are positive-signal observations (defense-in-depth additions found in code that exceed the plan's declared minimums). They strengthen the threat register but are not required for any threat to close:

1. **CR-01 (constant-time API-key comparison)** — `src/artiscrapper/auth.py:67-74` uses `hmac.compare_digest` per-key in a loop, eliminating per-byte equality timing leaks that `key in API_KEYS` would expose. Not required by T-03-01-01 (which only specified "401 on missing/unknown") but a free upgrade.
2. **CR-03 (`/health/deep` gated by `verify_api_key`)** — `src/artiscrapper/main.py:292` extends auth to the expensive deep-health endpoint, preventing unauthenticated triggers of Chromium round-trips and outbound bearer-token-carrying GETs. Closes an SSRF / DoS knob outside the plan's explicit threat scope.
3. **WR-05 (narrowed Sentry tag exception catch + one-shot drift flag)** — `src/artiscrapper/logging_setup.py:21,55-69` strengthens T-03-01-05's `try/except Exception` mitigation by catching only `(AttributeError, RuntimeError)` and setting a one-shot `_sentry_tag_warned` so future SDK drifts surface ONCE in structured logs rather than being permanently silenced.
4. **WR-01 (challenge_backoff snapshot/revert on persist failure)** — `src/artiscrapper/challenge_backoff.py:191-204` ensures in-memory `_STATE` and the durable sqlite row stay consistent if `_persist` raises. Without this, a disk-full event during a block would let the gate re-open `60 * 2^N` seconds too early after restart.
5. **WR-02 (record_block / record_success failures swallowed at the route)** — `src/artiscrapper/main.py:501-504, 538-541` wrap observability writes in try/except so a transient sqlite error never turns a genuine block into an opaque 500 for the consumer.
6. **WR-07 (record_success only fires when ≥1 candidate survived)** — `src/artiscrapper/main.py:537-541` prevents a 200-with-zero-results edge case (consent interstitial that bypassed `_detect_block`) from prematurely resetting `retry_count=0` and reopening the gate.
7. **WR-03 (background-task strong-reference set)** — `src/artiscrapper/main.py:207, 668-670` retains a strong ref on the cache-write task so Python's GC cannot drop it mid-flight — protects cache integrity that Phase 2 read-side tests assumed.

---

## Verification Method

For each `mitigate` threat: grep'd the cited file/symbol pattern and read 5+ lines of surrounding context to confirm semantic intent (not just textual match).
For each `accept` threat: documented in the Accepted Risks Log above with rationale, mitigation in place, and re-evaluation trigger.
No `transfer` dispositions (T-03-02-07 is `accept` with a documented forward telemetry transfer note).

**Implementation files inspected (READ-ONLY):**
- `src/artiscrapper/auth.py`
- `src/artiscrapper/main.py`
- `src/artiscrapper/logging_setup.py`
- `src/artiscrapper/metrics.py`
- `src/artiscrapper/challenge_backoff.py`
- `src/artiscrapper/cache.py`
- `src/artiscrapper/config.py`
- `pyproject.toml`
- `uv.lock` (grep only)
- `compose.yml`
- `tests/test_footguns.py`

**Phase artifacts loaded:**
- `.planning/phases/03-robustness/03-01-PLAN.md` (threat block lines 522-548)
- `.planning/phases/03-robustness/03-01-SUMMARY.md`
- `.planning/phases/03-robustness/03-02-PLAN.md` (threat block lines 488-512)
- `.planning/phases/03-robustness/03-02-SUMMARY.md`

---
*Audit completed 2026-06-03 — all 21 threats resolved (16 mitigate VERIFIED + 5 accept ACCEPTED); 0 OPEN; 0 unregistered flags.*
