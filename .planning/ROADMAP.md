# Roadmap: artiscrapper

## Milestones

- ✅ **v0.1 MVP — Google + LLM curator** — Phases 1, 2, 3, 3.1 (shipped 2026-06-04, archived `.planning/milestones/v0.1-phases/`)
- 🚧 **v0.2 — Paridad Visual + Robustez del Parser** — Phases 0.2.1..0.2.5 (started 2026-06-05)

## Overview

`artiscrapper v0.2` cierra el gap medido empíricamente del parser SERP — el servicio actual pierde **+207% URLs reales** frente a lo que un humano ve en la SERP de Google (medición transversal sobre 5 queries comerciales, reporte `.planning/PARSER-VISUAL-PARITY-2026-06-05.md`). El milestone aplica 3 patches quirúrgicos (no rewrite arquitectónico), instala harness continuo para detectar drift por rotación de clases Google, agrega paginación page 2 para queries saturadas, evalúa SerpAPI como ground-truth opcional, y limpia carried tech debt de v0.1.

**Phase Numbering:** v0.2 usa el formato `0.2.X` para mantener semántica clara con el milestone. Phases 4 y 5 (Phase 4 Production Operations, Phase 5 Expansion) siguen deferred-by-design de v0.1.

## Phases

- [x] **Phase 1: Spike & Empirical Validation** - Answer 12 Phase-0-spike questions, capture fixtures, deliver Go/No-Go (no production code) (completed 2026-06-01, archived)
- [x] **Phase 2: MVP** - Endpoint `/search` end-to-end with all 53 v1 requirements, Docker image, tests, validated against PRD §10 success criteria (completed 2026-06-02, archived)
- [x] **Phase 3: Robustness** - Prometheus metrics, Sentry, rate-limit per API-key, challenge detection + backoff, degraded mode, fixture-based integration suite (completed 2026-06-03, archived)
- [x] **Phase 3.1: v0.1 close hygiene** - REQUIREMENTS.md traceability flip, SUMMARY frontmatter, X-API-Key e2e, degraded-mode TestClient, slowapi Pattern B, WR-01..04 cleanup (completed 2026-06-04, archived)
- [ ] **Phase 4: Production Operations** - Grafana dashboards, Loki, cache invalidation endpoint, tracing — deferred-by-design, gated on prod telemetry demand
- [ ] **Phase 5: Expansion** - Per-supplier adapters, residential proxy, async+SSE, multi-tenant auth — deferred-by-design, gated on growth triggers
- [ ] **Phase 0.2.1: Parser Visual Parity** - Aplicar los 3 patches quirúrgicos del reporte (browser wait_until, regex precio v2, extractor pla-unit aditivo); +207% URLs reales medidas
- [ ] **Phase 0.2.2: Harness de Paridad Visual Continua** - Endpoint /admin/parity completo + 12 queries cross-vertical + métricas Prometheus + CI nightly + alertas
- [x] **Phase 0.2.3: Paginación Page 2** - Fetch page 2 en paralelo + dedupe por URL canónica pre-LLM + tests fixture-replay (completed 2026-06-05; runtime smoke + gain measurement deferred to operator via 0.2.3-HUMAN-UAT.md)
- [~] **Phase 0.2.4: SerpAPI Ground-Truth Spike** - ~~Spike 3 días evaluando SerpAPI como ground-truth del harness (~$1/mes); decisión documentada~~ **CANCELLED 2026-06-06** — viola la constraint del proyecto: no servicios pagos de ningún tipo. La ground truth es lo que el explorador renderiza (Cloak/browser); arreglar el render si se rompe, no cambiar fuente.
- [ ] **Phase 0.2.5: Carried Tech Debt v0.1** - tldextract 6.x, FastAPI ORJSONResponse cleanup, httpx2 test migration, scripts/spike/ ruff debt

## Phase Details

### Phase 0.2.1: Parser Visual Parity

**Goal**: Aplicar los 3 patches quirúrgicos del reporte (browser wait_until="load", regex precio v2 con cierre ,DD obligatorio, extractor `_extract_pla_unit()` aditivo al cascade actual) para subir URLs reales devueltas de 42 a 129 (+207%, medido en lab sobre 5 queries comerciales) sin penalty de latencia.

**Depends on**: Nothing — Estrategia A es self-contained y no toca LLM curator, freshness, ni cache.

**Requirements**: PARITY-01, PARITY-02, PARITY-03, PARITY-04, PARITY-05.

**Success Criteria** (observable, post-merge):

  1. `parse_serp(/tmp/toy-robotech.html)` retorna ≥4 candidates con flag `pla_unit` y URL canonical MELI (`mercadolibre.com.ar/.../p/MLA*` o `up/MLAU*`).
  2. `parse_serp(/tmp/ropa-zapatilla.html)` retorna ≥30 candidates con flag `pla_unit` y URL real no-Google (stores diversos: sporting, nike, stockcenter, etc.).
  3. `_PRICE_RE.search("$410.420,311001hobbies.es").group(0)` retorna `"$410.420,31"` — bug regression closed.
  4. `tests/test_parser.py::test_pla_unit_*` y `test_price_regex_*` pasan (≥9 tests nuevos, todos verdes).
  5. `GET /admin/parity/figura+coleccion+robotech` con X-API-Key responde 200 con `pla_unit_extracted ≥ 4` y `coverage_pct` calculado.

**Plans**: 2 plans

  - 0.2.1-01-PLAN — Parser core fixes (browser wait_until, regex precio v2, extractor pla-unit, nuevo pass en parse_serp)
  - 0.2.1-02-PLAN — Tests + fixtures + endpoint /admin/parity/{q} + métricas Prometheus mínimas

### Phase 0.2.2: Harness de Paridad Visual Continua

**Goal**: Detectar drift por rotación de clases Google / cambios upstream sin esperar a un humano que note el problema en prod. Dataset canónico + métricas + CI nightly + alertas.

**Depends on**: 0.2.1 (necesita el endpoint `/admin/parity/{query}` + las 2 métricas Prometheus mínimas ya declaradas).

**Requirements**: HARNESS-01, HARNESS-02, HARNESS-03, HARNESS-04, HARNESS-05.

**Success Criteria**:

  1. Dataset de 12 queries cross-vertical persistido en `tests/fixtures/parity-dataset.yaml` (6 verticales × 2 niveles specificity: toy/auto/electro/ropa/libro/electronica).
  2. 3 métricas Prometheus completas registradas: `parity_coverage_pct{query}`, `parity_pla_units_missed{query}`, `parity_url_synthetic_ratio{query}`, visibles en `/metrics`.
  3. Sample asincrónico 1/10 sobre hot path productivo: overhead p99 <50ms medido contra baseline pre-v0.2.
  4. CI nightly `parity-nightly.yml` corre el dataset y falla cuando coverage promedio <75%.
  5. Alertas Prometheus declaradas: `ParityCoverageWarn` (75% por >30min) y `ParityCoverageFail` (50% por >5min) en `prometheus/alerts/parity.yaml`.

**Plans**: TBD (definir en `/gsd-plan-phase 0.2.2`)

### Phase 0.2.3: Paginación Page 2

**Goal**: Capturar el catálogo Google que page 1 corta para queries con muchos candidates. Mediciones del reporte muestran que queries como `electro-termotanque` y `ropa-zapatilla` saturan a 30 pla-units en page 1 — claramente hay más en page 2 que el parser actual nunca toca.

**Depends on**: 0.2.1 (necesita el parser nuevo con extractor pla-unit funcional). Puede correr en paralelo con 0.2.2 una vez 0.2.1 cierre.

**Requirements**: PAGE2-01, PAGE2-02, PAGE2-03.

**Success Criteria**:

  1. `build_serp_url(query, meli, page=2)` produce URL con `&start=10` correctamente.
  2. `/search` fetcha page 1 y page 2 en paralelo respetando el rate-limiter; medición empírica confirma no incrementa rate de CAPTCHA.
  3. Dedupe pre-LLM por URL canónica: un producto en page 1 y page 2 se cuenta UNA vez; validado por test fixture.
  4. 2 fixtures page-2 capturadas (organic-heavy + pla-heavy) + integration tests miden gain incremental (>0 candidates únicos en page 2 sobre las 5 queries del dataset).

**Plans**: TBD

### Phase 0.2.4: SerpAPI Ground-Truth Spike — CANCELLED 2026-06-06

**Status**: CANCELLED — la phase asumía un servicio SaaS pago (SerpAPI ~$1-86/mes según cadencia y vendor) que viola la constraint del proyecto "no servicios pagos de ningún tipo" (ver `feedback_no_paid_services` en memoria del agente). La ground truth del proyecto es lo que el explorador renderiza (Cloak/browser); si se rompe, se arregla el render — no se cambia la fuente.

**Original goal (para forensics)**: Evaluar si SerpAPI / Bright Data SERP API puede actuar como ground-truth del harness continuo a costo ~$1/mes (12 queries × 1/hora), eliminando dependencia de Cloak para auditoría continua y desacoplando monitor del riesgo de CAPTCHA productivo.

**Requirements removed**: SERPAPI-01, SERPAPI-02 → cancelled, REQUIREMENTS.md flagged.

**If the underlying problem (Cloak drift / CAPTCHA rate) ever materializes**: la respuesta NO es spike-SerpAPI. Opciones browser-based aceptables: (a) endurecer Cloak settings, (b) rotar UA/locale más agresivo, (c) browser pool con recycle más temprano, (d) explorar Playwright directo + stealth libs free, (e) capturar fixtures congeladas adicionales y correr el harness offline contra ellos. Cualquier path debe ser browser-rendered, no API SaaS.

### Phase 0.2.5: Carried Tech Debt v0.1

**Goal**: Cerrar los 4 ítems de tech debt arrastrados desde v0.1 antes de que se acumule más en v0.3+.

**Depends on**: Ninguna — corre en paralelo con cualquier phase.

**Requirements**: TECHDEBT-01, TECHDEBT-02, TECHDEBT-03, TECHDEBT-04.

**Success Criteria**:

  1. tldextract bumpeada a 6.x; tests WR-01 (MELI guard) verdes; `grep -rn 'registered_domain' src/` retorna 0 matches del attr viejo.
  2. FastAPI ORJSONResponse: decisión documentada (default global vs explícito por endpoint) + código alineado a la decisión.
  3. httpx2 test migration: `pytest -q -W error::DeprecationWarning -m "not slow"` exits 0.
  4. scripts/spike/ ruff clean: `ruff check scripts/spike/` exits 0 sin warnings.

**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Spike & Empirical Validation | v0.1 | 3/3 | Complete (archived) | 2026-06-01 |
| 2. MVP | v0.1 | 3/3 | Complete (archived) | 2026-06-02 |
| 3. Robustness | v0.1 | 2/2 | Complete (archived) | 2026-06-03 |
| 3.1. v0.1 Close Hygiene | v0.1 | 3/3 | Complete (archived) | 2026-06-04 |
| 4. Production Operations | (deferred) | 0/TBD | Deferred-by-design | - |
| 5. Expansion | (deferred) | 0/TBD | Deferred-by-design | - |
| 0.2.1. Parser Visual Parity | v0.2 | 0/2 (scaffolded) | Planned | - |
| 0.2.2. Harness Paridad Continua | v0.2 | 0/TBD | Pending | - |
| 0.2.3. Paginación Page 2 | v0.2 | 2/2 | Complete (runtime UAT pending) | 2026-06-05 |
| 0.2.4. SerpAPI Ground-Truth Spike | v0.2 | 0/0 | CANCELLED (paid service constraint) | 2026-06-06 |
| 0.2.5. Carried Tech Debt v0.1 | v0.2 | 0/TBD | Pending | - |

## Coverage Check

v0.2 declara **19 REQ-IDs** originales; **17 activos** tras la cancelación de 0.2.4 el 2026-06-06 (SERPAPI-01..02 también cancelados):

- PARITY-01..05 → Phase 0.2.1
- HARNESS-01..05 → Phase 0.2.2
- PAGE2-01..03 → Phase 0.2.3
- ~~SERPAPI-01..02~~ → Phase 0.2.4 **CANCELLED** (paid service constraint)
- TECHDEBT-01..04 → Phase 0.2.5

Phases 4 + 5 (deferred-by-design de v0.1) continúan sin v0.2 requirements asignados.

## Archives

- `.planning/milestones/v0.1-phases/` — phase docs de v0.1 (01-spike, 02-mvp, 03-robustness, 03.1-close-hygiene)
- `.planning/milestones/v0.1-ROADMAP.md` — roadmap original v0.1
- `.planning/milestones/v0.1-REQUIREMENTS.md` — requirements v0.1 con final SATISFIED status
- `.planning/milestones/v0.1-MILESTONE-AUDIT.md` — audit post-3.1 (status `passed`)
- `.planning/MILESTONES.md` — log histórico de milestones
