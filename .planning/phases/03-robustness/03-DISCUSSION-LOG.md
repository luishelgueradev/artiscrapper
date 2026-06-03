# Phase 3: Robustness - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-03
**Phase:** 3-Robustness
**Areas discussed:** API key + rate-limit, ChallengeBackoff scope + reset, /metrics auth, Sentry config

---

## API Key Authentication & Rate-Limit Policy

PRD doesn't fix how consumers authenticate or the per-key quota. Client expectation: Sánchez Repuestos (1 client, ~500-2000 q/day).

| Option | Description | Selected |
|--------|-------------|----------|
| Static keys in env-var | `API_KEYS=k1,k2,k3` (rotation = restart). KISS for 1 client. Quota proposed: 60/min + 10000/day per-key. | ✓ |
| sqlite-backed keys table + admin endpoint | Dynamic via `POST /admin/keys`. More flexible but requires admin auth + UI/CLI. Worth it if onboarding more clients in Phase 4. | |
| Bearer JWT (signed) | Overkill for 1 client; requires issuer/refresh infrastructure. | |

**User's choice:** Static keys (Recommended).
**Notes:** Captured as D-01 through D-04 in CONTEXT.md. Quota (60/min + 10000/day) gives ~5× headroom over expected peak — explicit guard against runaway consumer traffic blowing out the per-instance Cloak 1/min rate-limit.

---

## ChallengeBackoff Scope + Reset Trigger

ROADMAP locks the backoff curve `min(60s × 2^retries, 1h)` and sqlite persistence. Open: how the counter resets, and whether scope is global to Google or per-host.

| Option | Description | Selected |
|--------|-------------|----------|
| Global to Google, reset after 1h clean | Single counter for all `*.google.com`. Reset = first successful fetch ≥1h after last block. | ✓ |
| Global, reset after N=5 consecutive successes | More sensitive to real SERP state. Requires extra success counter. | |
| Per-host (query A vs B SERP tracked separately) | Independent tracks for `query` vs `query mercadolibre`. More code; dubious value — Google blocks are IP-level. | |

**User's choice:** Global + 1h clean reset (Recommended).
**Notes:** Captured as D-05 through D-09 in CONTEXT.md. Matches Google's typical IP-cool-off window; avoids state explosion of tracking success counters. Per-host explicitly rejected and recorded in Deferred Ideas.

---

## `/metrics` Endpoint Auth

Prometheus scraper typically runs internal; `/metrics` exposes commercial counters (LLM cost, visit failures per host).

| Option | Description | Selected |
|--------|-------------|----------|
| No auth | Free access from internal docker network. If container is ever exposed publicly, reverse-proxy enforces IP allowlist. KISS for Phase 3. | ✓ |
| Bearer (same as `Authorization`) | Reuses LLM router pattern. Couples Prometheus scraper config to the bearer rotation. | |
| Separate header (`X-Metrics-Token`) | Isolated rotation. Adds another credential surface. | |

**User's choice:** No auth (Recommended).
**Notes:** Captured as D-10 in CONTEXT.md. Defensible for single-container deploy. Bearer/IP-allowlist deferred to a future phase if/when the container is exposed beyond the internal docker network.

---

## Sentry Sample Rates + Env Routing

| Option | Description | Selected |
|--------|-------------|----------|
| Off default; `SENTRY_DSN` optional with `traces=0.1`, `profiles=0` | If DSN absent → no init. When set: errors 100%, traces 10% (detect regressions without saturating free plan), profiles off (expensive). | ✓ |
| Off default; when set: errors 100%, traces 0, profiles 0 | Minimum absolute: only uncaught errors, no perf metrics. Recommended for strict free-tier. | |
| Multi-env (`SENTRY_DSN_DEV` / `_STAGING` / `_PROD`) | Routing by `APP_ENV`. Worth it if you already have multiple Sentry projects. Overkill for 1 client / 1 environment. | |

**User's choice:** Off default + balanced sample rates (Recommended).
**Notes:** Captured as D-14 through D-17 in CONTEXT.md. Multi-env explicitly rejected and recorded in Deferred Ideas (but the env-var name pattern leaves room for an `APP_ENV` tag without restructuring).

---

## Claude's Discretion

The following implementation details were left for the researcher/planner to decide based on current library docs and existing code patterns:

- `slowapi` middleware ordering vs `CorrelationIdMiddleware` and FastAPI exception handlers (constraint: correlation_id must be available in Sentry breadcrumbs even on 429 responses)
- `challenge_state` sqlite schema details (single-row upsert pattern, lock semantics)
- `slowapi` `default_limits` vs per-route decorators (whichever produces cleaner config without duplication)
- Sentry SDK version + which integrations to enable (FastAPI canonical; Httpx optional)

## Deferred Ideas

- **Per-host ChallengeBackoff scope** — rejected; Google blocks are IP-level. Revisit only if asymmetric block behavior observed in production.
- **Admin endpoint for dynamic API key creation/revocation** — deferred to Phase 4 if additional consumers are onboarded.
- **Multi-environment Sentry routing** (`SENTRY_DSN_DEV` / `_STAGING` / `_PROD`) — rejected for current scope (single-environment).
- **Bearer / IP-allowlist on `/metrics`** — deferred until container is exposed beyond internal docker network.
- **Distributed rate-limit store (Redis)** — out of scope; violates 1-container architecture.
- **`slowapi` sliding-window quota algorithm** — fixed-window default is acceptable for 60/min; revisit only if abuse patterns appear.
- **Phase 2 cleanup items from `02-REVIEW.md`** (WR-01 MELI substring, WR-02 cache-write strong ref, WR-04 temp file cleanup) — opportunistic, not gating Phase 3.
