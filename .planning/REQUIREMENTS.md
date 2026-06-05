# Milestone v0.2 Requirements — Paridad Visual + Robustez del Parser

**Milestone:** v0.2 (2026-06-05 →)
**Project:** artiscrapper
**Source:** evidencia empírica `.planning/PARSER-VISUAL-PARITY-2026-06-05.md` (Exp 1-4 cerrados desatendido 2026-06-05) + carried tech debt de v0.1
**Goal:** cerrar el gap medido de paridad visual del parser SERP (+207% URLs reales pérdidas, +74% precios pérdidos), instalar harness continuo para detectar drift, y limpiar tech debt de v0.1.

## v1 Requirements (this milestone)

### Parser Visual Parity (Estrategia A — 3 patches quirúrgicos)

- [ ] **PARITY-01**: `src/artiscrapper/browser.py` usa `wait_until="load"` (no `domcontentloaded`) + timeout 15s para que Cloak renderice el Shopping panel `div.pla-unit` antes de devolver HTML.
- [ ] **PARITY-02**: `src/artiscrapper/search.py` expone `_extract_pla_unit(node)` + `PLA_SELECTORS = ["div.pla-unit"]` y `parse_serp()` corre un pass adicional pla-unit DESPUÉS del carousel loop, aditivo (no reemplaza organic cascade).
- [ ] **PARITY-03**: `_PRICE_RE` en `search.py` matchea `$X.XXX,XX` con cierre `,DD` obligatorio + alternativa entero (`ARS 5000`, `U$S 5000`), cerrando el bug `$410.420,311001` reproducible con texto `$ 410.420,31` + nombre de store con dígitos.
- [ ] **PARITY-04**: 2 fixtures HTML capturadas en `tests/fixtures/serp/` (`pla_unit_robotech.html`, `pla_unit_zapatillas.html`) + 9 unit tests (`test_pla_unit_*`, `test_price_regex_*`) + 4 integration tests fixture-replay en `tests/integration/test_serp_pla_unit_replay.py`, todos pasando.
- [ ] **PARITY-05**: endpoint `GET /admin/parity/{query}` autenticado con X-API-Key registrado en `main.py`, retorna JSON con `html_metrics` + `parser_metrics` + `drift`; 2 métricas Prometheus mínimas registradas (`artiscrapper_parity_pla_units_in_html`, `artiscrapper_parity_pla_units_extracted`).

### Harness de Paridad Visual Continua

- [ ] **HARNESS-01**: dataset canónico de 12 queries cross-vertical persistido en `tests/fixtures/parity-dataset.yaml` o equivalente: 6 verticales × 2 niveles specificity (toy/auto/electro/ropa/libro/electronica × espec/broad).
- [ ] **HARNESS-02**: métricas Prometheus completas registradas: `artiscrapper_parity_coverage_pct{query}`, `artiscrapper_parity_pla_units_missed{query}`, `artiscrapper_parity_url_synthetic_ratio{query}`, scrapeable desde `/metrics`.
- [ ] **HARNESS-03**: sample asincrónico 1/10 sobre tráfico productivo de `/search`: cada décima query corre el audit en background sin bloquear la respuesta, overhead p99 <50ms medido.
- [ ] **HARNESS-04**: GitHub Actions workflow `parity-nightly.yml` corre el dataset de 12 queries vía `compose up` ephemeral, agrega coverage promedio y falla CI si <75%.
- [ ] **HARNESS-05**: alertas Prometheus declaradas: `ParityCoverageWarn` (75% por >30min) y `ParityCoverageFail` (50% por >5min) en `prometheus/alerts/parity.yaml` (o equivalente).

### Paginación Page 2

- [x] **PAGE2-01**: `build_serp_url(query, meli, page=N)` extendido con parámetro `page` que genera `&start=10*N` y `parse_serp` corre dos pages en paralelo via `asyncio.gather` (rate-limiter respetado). _(closed 2026-06-05, phase 0.2.3 plan 01)_
- [x] **PAGE2-02**: dedupe global por URL canónica antes del LLM curator: si page 1 y page 2 tienen el mismo producto/MELI ID, se cuenta una vez. Test fixture-replay valida la deduplicación. _(closed 2026-06-05, phase 0.2.3 plan 02)_
- [x] **PAGE2-03**: 2 fixtures HTML page 2 capturadas (organic-heavy + pla-heavy) + integration tests que verifican el gain incremental real medido. _(closed 2026-06-05, phase 0.2.3 plan 02; live gain measurement deferred to 0.2.3-HUMAN-UAT.md)_

### SerpAPI Ground-Truth Spike

- [ ] **SERPAPI-01**: spike de 3 días: cliente httpx para SerpAPI + adapter que mapea respuesta SerpAPI al schema de candidates, corrido contra el dataset de 12 queries. Output: comparación tabular vs Cloak parsing.
- [ ] **SERPAPI-02**: decisión documentada en `.planning/SERPAPI-DECISION-2026-XX-XX.md`: integrar SerpAPI como fuente del harness continuo (~$1/mes para 12 queries × 1/hora) o defer indefinidamente, con justificación basada en los números del spike.

### Carried Tech Debt v0.1

- [ ] **TECHDEBT-01**: tldextract 5.3.1 → 6.x — rename `.registered_domain` → `.top_domain_under_public_suffix` en `src/artiscrapper/visit.py` y donde sea que lo use; tests existentes (WR-01 MELI guard) siguen pasando.
- [ ] **TECHDEBT-02**: FastAPI ORJSONResponse cleanup — auditar uso, decidir si default global vs explícito por endpoint, documentar.
- [ ] **TECHDEBT-03**: httpx2 test migration — actualizar tests que usen API httpx vieja (deprecation warnings clean).
- [ ] **TECHDEBT-04**: scripts/spike/ ruff debt — limpiar warnings ruff en scripts/spike/, decidir si archivar o mantener bajo lint.

## Future Requirements (post-v0.2)

Triggered cuando aparezca el signal correspondiente; no scope v0.2.

- **Estrategia B — DOM-driven browser persistente**: viola D8 invariant; sin caso de uso económicamente convincente.
- **Carousel URL real via JS-render**: depende de Estrategia B o SerpAPI; no autónomamente viable.
- **Phase 4 (Production Operations)**: Grafana + Loki + cache invalidation + OTel tracing. Gated en prod telemetry demand (P95 cold >40s sustained, per-host visit_failed >30%, demanda explícita de Grafana boards).
- **Phase 5 (Expansion)**: per-supplier adapters, residential proxy, /search/stream SSE, multi-tenant auth. Gated en growth triggers (Google IP-block rate >5%/day, segundo cliente, P95 cold sustained >40s).

## Out of Scope (this milestone)

- **Rewrite del parser** — el reporte cierra que Estrategia A (3 patches quirúrgicos) cubre el 90% del gap con LOC mínimo. NO rewrite.
- **Cambios al LLM curator, freshness, cache** — fuera del scope del fix de parser.
- **Nuevos endpoints públicos** — `/admin/parity/{query}` es admin-only.
- **Scraping directo de MercadoLibre** — sigue out of scope post-v0.1.
- **Proxy residencial / IP rotation** — gated en Phase 5 trigger.
- **Multi-tenant auth** — gated en Phase 5 trigger.

## Traceability

Filled by the roadmap during `/gsd-plan-phase` cycles. Initial mapping (decidido en este milestone-start):

| REQ-ID | Phase | Status |
|---|---|---|
| PARITY-01..05 | 0.2.1 | Pending |
| HARNESS-01..05 | 0.2.2 | Pending |
| PAGE2-01..03 | 0.2.3 | Complete (2026-06-05; runtime UAT pending) |
| SERPAPI-01..02 | 0.2.4 (opcional/spike) | Pending |
| TECHDEBT-01..04 | 0.2.5 | Pending |

---

*Defined: 2026-06-05*
*Source: `.planning/PARSER-VISUAL-PARITY-2026-06-05.md` (empirical evidence) + carried tech debt v0.1*
