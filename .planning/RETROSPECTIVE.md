# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v0.1 — MVP — Google + LLM curator

**Shipped:** 2026-06-04
**Phases:** 4 (1 Spike + 2 MVP + 3 Robustness + 3.1 v0.1 close hygiene) | **Plans:** 11 | **Sessions:** ~4 main + several follow-ups

### What Was Built

- End-to-end `POST /search` pipeline: 2 parallel Google fetches via Cloakbrowser singleton with ephemeral `new_context()` per request, parser cascade with `parse.cascade.exhausted` alert, junk-domain blocklist pre-filter, Spanish LLM curator with Semaphore(4) + `<0.4` confidence cutoff + degraded-mode price-in-card fallback, conditional visit pass with hand-rolled JSON-LD/OG/microdata/AR-regex extractor, freshness assessment, re-rank, aiosqlite WAL cache with gzipped BLOBs + lazy TTL + hourly prune.
- Production resilience: X-API-Key auth with `hmac.compare_digest`, slowapi Pattern B rate-limit (module constants → decorator argument + log line, drift impossible by construction), Google ChallengeBackoff state machine with sqlite persistence surviving container restart, 503+Retry-After when gate denies.
- Observability: structlog JSON with `merge_contextvars` + correlation_id, `/metrics` ASGI sub-app exposing 12 canonical `artiscrapper_*` Prometheus families + workload-tuned Histograms, env-gated Sentry SDK with correlation_id tag injection.
- Deploy: single-image Dockerfile multi-stage with `cloakhq/cloakbrowser:0.3.31` + Chromium pin, `tini`/`--init`, `uv.lock`, `compose.yml` with sqlite bind-mount, CI-asserted no-uvloop + no-persistent_context invariants.
- 55/55 v1 REQ-IDs SATISFIED across 9 categories; 10/10 cross-phase integration WIRED; 5/5 E2E flows PASS; 68 unit + 9 integration + 2 E2E-gated tests green; mypy --strict on `src/artiscrapper/` clean.

### What Worked

- **Phase 1 spike as empirical gate before Phase 2 lock-in**: 12 open questions answered with fixtures (10 SERP + 10 catalog PDP + 50 hand-labeled candidates) AND a written Go/No-Go (`SPIKE.md`) BEFORE production code started. Phase 2 didn't fly blind on D1 (Cloak Docker pin), D8 (no persistent_context), D10 (LLM concurrency = 4), D11 (httpx 403 rate), D12 (hand-roll JSON-LD).
- **3-source cross-reference (REQUIREMENTS.md / SUMMARY.md / VERIFICATION.md)** caught traceability drift at audit time. Phase 3.1 closed the bookkeeping debt before milestone-close, not after.
- **Foot-gun memory file with D2/D6/D8 surfaced at every plan**: D2 LLM `confidence=0.3` IS dropped at `<0.4` cut; D6 uvloop ban + CI grep assertion; D8 no `launch_persistent_context` + footgun test. Three load-bearing invariants that survived every refactor.
- **Empirical verification (Phase 3 UAT, Phase 3.1 D-06)** caught regressions that unit tests couldn't: ChallengeBackoff state survives `compose up --force-recreate`; slowapi `default_limits` doesn't fire without SlowAPIMiddleware (Pattern A non-viable on slowapi 0.1.9 + FastAPI).
- **Atomic per-task commits** with verify gates between commits: every task ran the per-task `<verify>` block before commit; full-suite re-test after each task. When Wave 2 Plan 03.1-02 Task 2 introduced a shared-sqlite isolation bug under full-suite ordering, it was caught and root-caused (not assertion-relaxed) immediately.
- **Research-before-planning when research enabled**: gsd-phase-researcher pre-empted Phase 3.1 Pattern A failure by reading slowapi source code AND Context7 docs — but Context7 alone wasn't enough to prove Pattern A worked. The executor's empirical re-attempt + revert + Pattern B switch was the right escalation.
- **Phase 3.1 D-09 WR-02 verify-only finding**: researcher caught that the audit text referenced pre-Phase-3 line numbers; re-emitting a fix would have produced a no-op diff and falsely claimed a fix. Verify-only commit (no source diff) was the correct closure.
- **Memory files (`feedback_*`)** carried operationally important constraints into the right plan moment: `feedback_compose_build_recreate` for D-06 retest separation, `feedback_agent_as_uat_operator` for who runs the checkpoint, `feedback_empirical_retest_after_default_changes` for why a settings-source-of-truth refactor (not telemetry band-aid) was required.

### What Was Inefficient

- **Pre-3.1 audit numbers were stale (`53 logical`) vs actual table (`55 REQ-IDs`)**: the audit reproduced the ROADMAP framing without verifying against the live table. Plan 03.1-01 verify gate expected `== 53` and the executor surfaced the discrepancy AFTER applying changes. Root-cause: audit didn't run a count grep against the live file before authoring the verify command. Cost: ~10 minutes of confusion + one reconciliation commit.
- **Pattern A research outpaced empirical verification**: Context7 docs documented `default_limits=[...]` and the research recommended it; the executor applied it; tests regressed; revert + Pattern B took ~10 minutes of extra work that could have been avoided if the research itself had a Pattern A smoke probe (1 line `Limiter(default_limits=[...])` + 1 HTTP test against a decorated route) as a hard gate before recommendation.
- **3.1 SUMMARYs I wrote used hyphen form (`requirements-completed`)** vs underscore form used by the rest of the project + audit tool convention. Caught at milestone-audit time and normalized; root-cause: I copied the template literally without converting the key, and the template at `~/.claude/get-shit-done/templates/summary.md` itself shows `requirements-completed:` (line 41).
- **Stale comments in `compose.yml` and `.env.example`** about slowapi being "informational, uses string literals" survived from Phase 3 into Phase 3.1 D-05. Caught only at the end of Plan 03.1-03 D-06 retest, not by the refactor task itself. Lesson: refactor tasks should grep for stale doc references in companion ops files.
- **The MILESTONES.md auto-archival only counted Phase 3.1's 3 plans** as the milestone scope (`1 phase, 3 plans, 13 tasks`). I had to manually enrich with the full 4-phase 11-plan scope. Likely the SDK `milestone.complete` query only counts non-archived phase directories with `disk_status === 'complete'` — Phases 1, 2, 3 were already excluded from the active count.
- **Two `feedback_*` memories formed mid-milestone** (`feedback_agent_as_uat_operator`, `feedback_compose_build_recreate`) — both could have been crystallized earlier. The compose memory came from a 25min wasted build cycle; the UAT operator memory came from explicit user direction.

### Patterns Established

- **Pattern B settings-source-of-truth (slowapi)**: module-level f-string constant computed from settings at import; used by both `@limiter.limit()` decorator argument AND structlog kwarg in lifespan log; drift surface = 1 line. Recommended for any future "wire settings into decorator-style API" refactor on slowapi 0.1.x.
- **3-source cross-reference (REQUIREMENTS.md / SUMMARY.requirements_completed / VERIFICATION.md)** as the milestone-audit invariant. Set-union must equal table size. Caught Phase 3.1's hygiene debt cleanly.
- **Per-phase Acceptance Rationale section in VALIDATION.md** body (3 phase-specific bodies inline) for Nyquist accept without retroactive wave-0 generation. Useful when phases are empirically passed but missing the formal wave-0 artifact.
- **WR-02-style verify-only commits** (no source diff, grep-evidence commit message) when an audit item is found already-implemented. Avoids no-op diffs falsely claiming fixes.
- **D-06-style empirical retest with operator UAT**: bump `.env` → `compose build` (separate from `up`) → `compose up -d --force-recreate` → grep log line → exercise endpoint N times → assert N+1th fails → revert `.env`. Cheap, deterministic, catches shadowing across settings/contract/route layers that unit tests miss.
- **`feedback_agent_as_uat_operator` pattern**: for checkpoints that need shell + docker compose + curl loops, Claude runs the UAT himself rather than pausing for the human. Memory makes this the default.

### Key Lessons

1. **Empirical gates beat documentation gates for library APIs**. Pattern A read fine in Context7 docs but didn't work in production runtime. Research-before-planning is good; research-with-empirical-smoke-probe is better. When a research finding is load-bearing for the plan, the research should include a minimum-viable runtime probe.
2. **Audit numbers must be re-verified against live files at audit time**. The pre-3.1 audit framed v0.1 as "53 reqs" because the ROADMAP said so; the live table had 55. Audit verifies must `grep -c` the live file, not echo prior framing.
3. **Hygiene phases are real work and deserve real planning**. Phase 3.1 looked like "5 tech_debt items + 4 WRs = trivial", but it surfaced a load-bearing slowapi refactor (Pattern A → B) and a permanent normalization decision (hyphen → underscore frontmatter key) that wouldn't have been caught by a quick-fix sweep.
4. **Deferred-by-design is a first-class milestone outcome**, not a failure mode. Phases 4 and 5 shipped with 0 v1 reqs by explicit design. The milestone-close ceremony recorded them as `deferred-by-design — re-evaluated for v0.2 trigger conditions`, preserving the roadmap shape without forcing a scope-rewrite or false-completion claim.
5. **Strong-ref pattern for `asyncio.create_task` is a load-bearing GC-safety invariant** — the Phase 3 fix at `main.py:212 / 695-696` was the right kind of structural defense that doesn't get caught by tests but does get caught by GC under load. The pattern is now project-canonical.
6. **Foot-gun memories surfaced at every plan** are worth their weight. D2, D6, D8 were named foot-guns from day one and survived every refactor; no regression slipped through.

### Cost Observations

- Model mix: predominantly **Claude Opus 4.7 (1M context)** as orchestrator + research; **Claude Sonnet** as executor/researcher/planner/verifier subagents (gsd config `model_profile: balanced`).
- Sessions: ~4 main work sessions over 3 days + several smaller follow-ups (audit, close-milestone).
- Notable: **The autonomous Phase 3.1 + audit + close cycle ran in ~3 hours total** without user supervision. Subagent isolation (`gsd-executor`, `gsd-phase-researcher`, `gsd-plan-checker`, `gsd-integration-checker`) kept the orchestrator context lean; each subagent saw only its own task spec + relevant files.
- **Empirical retest cycle is non-trivial cost**: D-06 alone was a ~25-second docker compose build + ~10-second up + ~5-second curl loop + revert. ~1 minute of wall clock for a load-bearing verification. Worth every second.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v0.1 | ~4 | 4 | Established baseline: spike-gated empirical Phase 1; YOLO mode autonomous Phase 2-3; INSERTED Phase 3.1 for hygiene close; deferred-by-design for Phases 4-5 |

### Cumulative Quality

| Milestone | Tests | Coverage | Zero-Dep Additions |
|-----------|-------|----------|--------------------|
| v0.1 | 68 unit + 9 integration + 2 E2E gated = 79 total | mypy --strict clean on src/artiscrapper/; ruff + format clean on phase-touched files | 0 new deps in Phase 3.1 (reused tldextract 5.3.1 already pinned) |

### Top Lessons (Verified Across Milestones)

1. **Empirical gates > documentation gates** for library APIs (Pattern A→B story is the canonical example; verified once in v0.1, will need cross-milestone confirmation in v0.2).
2. **3-source cross-reference catches bookkeeping drift before milestone close** (verified in v0.1; worth standardizing for v0.2).
3. **Hygiene phases (INSERTED decimals) are real work** — v0.1's Phase 3.1 took 3 plans / ~3 hours and was load-bearing for milestone close. Plan as first-class work, not afterthought.
