# Roadmap: artiscrapper

## Milestones

- ✅ **v0.1 MVP — Google + LLM curator** — Phases 1, 2, 3, 3.1 (shipped 2026-06-04, archived `.planning/milestones/v0.1-phases/`)
- 🚧 **v0.2 — Paridad Visual + Robustez del Parser** — Phases 0.2.1..0.2.5 (started 2026-06-05)

## Phases

<details>
<summary>✅ v0.1 MVP — Google + LLM curator (shipped 2026-06-04)</summary>

- [x] Phase 1: Spike & Empirical Validation — completed 2026-06-01
- [x] Phase 2: MVP — completed 2026-06-02
- [x] Phase 3: Robustness — completed 2026-06-03
- [x] Phase 3.1: v0.1 close hygiene (INSERTED) — completed 2026-06-04

Archived phase docs: `.planning/milestones/v0.1-phases/`.
Archived audit: `.planning/milestones/v0.1-MILESTONE-AUDIT.md` (status `passed`, 55/55 v1 reqs).

**Deferred-by-design (no v1 reqs assigned):**
- ⏭ Phase 4: Production Operations — re-evaluated at v0.2 entry, **still deferred** (no Grafana/Loki demand yet).
- ⏭ Phase 5: Expansion — re-evaluated at v0.2 entry, **still deferred** (no Google block rate, no 2nd consumer).

</details>

### 🚧 v0.2 — Paridad Visual + Robustez del Parser (current)

Started 2026-06-05. Evidence-driven (reporte `.planning/PARSER-VISUAL-PARITY-2026-06-05.md`).
**Goal global:** subir URLs reales devueltas en producción de 42 a 129 (+207%, medido en lab sobre 5 queries) sin penalty de latencia, instalar monitor continuo para drift, cerrar carried tech debt v0.1.

#### Phase 0.2.1 — Parser Visual Parity (Estrategia A patches) — DRAFT READY

**Goal:** Aplicar los 3 patches quirúrgicos del reporte para cerrar el gap de URLs reales del parser SERP.

**Requirements:** PARITY-01, PARITY-02, PARITY-03, PARITY-04, PARITY-05.

**Success criteria** (observable, post-merge):
1. `parse_serp(/tmp/toy-robotech.html)` retorna ≥4 candidates con flag `pla_unit` y URL canonical MELI.
2. `parse_serp(/tmp/ropa-zapatilla.html)` retorna ≥30 candidates con flag `pla_unit` y URL real no-Google.
3. `_PRICE_RE.search("$410.420,311001hobbies.es").group(0)` retorna `"$410.420,31"` (bug fix).
4. `tests/test_parser.py::test_pla_unit_*` y `test_price_regex_*` pasan (≥9 tests nuevos).
5. `GET /admin/parity/figura+coleccion+robotech` con X-API-Key responde 200 con `pla_unit_extracted ≥ 4`.

**Plans (ya borradores en `.planning/drafts/0.2.1-parser-visual-parity/`):**
- 0.2.1-01-PLAN — Parser core fixes (browser wait_until + regex precio + extractor pla-unit)
- 0.2.1-02-PLAN — Tests + fixtures + endpoint `/admin/parity/{q}` + métricas mínimas

**Status:** plan-phase autonómo dejó draft completo el 2026-06-05; promoverlo con `mv .planning/drafts/0.2.1-parser-visual-parity .planning/phases/0.2.1-parser-visual-parity` y arrancar `/gsd-execute-phase 0.2.1`.

#### Phase 0.2.2 — Harness de Paridad Visual Continua

**Goal:** detectar drift por rotación de clases Google / cambios upstream sin esperar a un humano que note el problema en prod.

**Requirements:** HARNESS-01, HARNESS-02, HARNESS-03, HARNESS-04, HARNESS-05.

**Success criteria:**
1. Dataset de 12 queries cross-vertical persistido en repo (`tests/fixtures/parity-dataset.yaml` o equivalente).
2. 3 métricas Prometheus completas declaradas: `parity_coverage_pct{query}`, `parity_pla_units_missed{query}`, `parity_url_synthetic_ratio{query}`, visibles en `/metrics`.
3. Sample 1/10 sobre hot path productivo: overhead p99 <50ms (medido contra baseline pre-v0.2).
4. CI nightly `parity-nightly.yml` corre el dataset y falla cuando coverage promedio <75%.
5. Alertas Prometheus declaradas: `ParityCoverageWarn` (75%) y `ParityCoverageFail` (50%) en `prometheus/alerts/parity.yaml`.

**Depends on:** 0.2.1 (necesita el endpoint `/admin/parity/{query}` + métricas mínimas).

#### Phase 0.2.3 — Paginación Page 2

**Goal:** capturar el catálogo Google que page 1 corta para queries con muchos candidates (electro-termotanque, ropa-zapatilla saturan a 30 pla-units en page 1).

**Requirements:** PAGE2-01, PAGE2-02, PAGE2-03.

**Success criteria:**
1. `build_serp_url(q, meli, page=2)` produce URL con `&start=10`.
2. `/search` fetcha page 1 y page 2 en paralelo respetando rate-limiter; no genera ban adicional medido.
3. Dedupe pre-LLM por URL canónica: un producto en page 1 y page 2 se cuenta UNA vez, validado por test.
4. 2 fixtures page-2 capturadas + integration tests miden gain incremental (>0 candidates únicos en page 2 sobre las 5 queries del dataset).

**Depends on:** 0.2.1 (necesita el parser nuevo para extraer correctamente). Puede correr en paralelo con 0.2.2.

#### Phase 0.2.4 — SerpAPI Ground-Truth Spike (CONDITIONAL)

**Goal:** evaluar si SerpAPI / Bright Data SERP API puede actuar como ground-truth del harness continuo a costo ~$1/mes, eliminando dependencia de Cloak para auditoría.

**Requirements:** SERPAPI-01, SERPAPI-02.

**Success criteria:**
1. Cliente httpx para SerpAPI + adapter mapping a schema candidates.
2. Comparación cuantitativa Cloak vs SerpAPI sobre dataset 12 queries (cobertura, latencia, costo).
3. Decisión final escrita en `.planning/SERPAPI-DECISION-2026-XX-XX.md` con tabla de tradeoffs y recomendación.

**Depends on:** 0.2.2 (necesita el dataset canónico para comparar).
**Conditional:** activar SOLO si el harness 0.2.2 muestra drift inestable o el rate de CAPTCHA productivo sube >5%/día. Si todo estable, defer indefinidamente.

#### Phase 0.2.5 — Carried Tech Debt v0.1 Cleanup

**Goal:** cerrar los 4 ítems de tech debt arrastrados de v0.1 antes de que se acumule más en v0.2/v0.3.

**Requirements:** TECHDEBT-01, TECHDEBT-02, TECHDEBT-03, TECHDEBT-04.

**Success criteria:**
1. tldextract bumpeada a 6.x; tests WR-01 (MELI guard) verdes; `grep -n 'registered_domain' src/` retorna 0 matches del attr viejo.
2. FastAPI ORJSONResponse: decisión documentada (default global vs explícito) + código alineado.
3. httpx2 test migration: `pytest -q -W error::DeprecationWarning -m "not slow"` exits 0.
4. scripts/spike/ ruff clean: `ruff check scripts/spike/` exits 0 sin warnings.

**Depends on:** ninguna (paralelo con cualquiera).

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 0.2.1 Parser Visual Parity | v0.2 | 0/2 (drafts ready) | Planned (DRAFT) | - |
| 0.2.2 Harness Paridad Continua | v0.2 | 0/TBD | Pending | - |
| 0.2.3 Paginación Page 2 | v0.2 | 0/TBD | Pending | - |
| 0.2.4 SerpAPI Ground-Truth Spike | v0.2 | 0/TBD | Conditional | - |
| 0.2.5 Carried Tech Debt | v0.2 | 0/TBD | Pending | - |

## Coverage Check

v0.2 declara **19 REQ-IDs** distribuidos así:
- PARITY-01..05 → Phase 0.2.1
- HARNESS-01..05 → Phase 0.2.2
- PAGE2-01..03 → Phase 0.2.3
- SERPAPI-01..02 → Phase 0.2.4
- TECHDEBT-01..04 → Phase 0.2.5

Cada REQ-ID mapea a exactamente una phase ✓. Coverage 100%.

Phase 4 + 5 (deferred-by-design de v0.1) continúan sin v0.2 requirements asignados.

## Archives

- `.planning/milestones/v0.1-phases/` — phase docs de v0.1 (01-spike, 02-mvp, 03-robustness, 03.1-close-hygiene)
- `.planning/milestones/v0.1-ROADMAP.md` — roadmap original v0.1
- `.planning/milestones/v0.1-REQUIREMENTS.md` — requirements v0.1 con final SATISFIED status
- `.planning/milestones/v0.1-MILESTONE-AUDIT.md` — audit post-3.1 (status `passed`)
- `.planning/MILESTONES.md` — log histórico de milestones
