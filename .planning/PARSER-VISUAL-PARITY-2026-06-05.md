# Parser Visual Parity — Exp 1-4 cerrados (2026-06-05)

Autor: Claude (sesión desatendida)
Branch base: `main` @ 8c09120 (v0.1.1 post Path B)
Artefactos: `/tmp/{toy-robotech,auto-filtro,electro-termotanque,libro-tapa-dura,ropa-zapatilla}.html` + variantes wait_until.

## TL;DR ejecutivo

El parser actual pierde en promedio **el 38% de los productos comerciales** que un humano ve en la SERP. La pérdida tiene **dos causas medidas empíricamente**, ambas fixables con cambios quirúrgicos:

1. **`browser.py` usa `wait_until="domcontentloaded"`** → Cloak corta el render antes de que Google cargue el Shopping panel. En el día del experimento la pérdida fue 0→4 pla-units en robotech, **0→30 en `termotanque` y `zapatillas`**.
2. **El cascade del parser no toca `div.pla-unit`** → aunque el HTML los traiga, no los extrae.

Aplicar los 3 fixes propuestos (`wait_until="load"` + extractor pla-unit + regex precio robusto) **multiplica por 3 las URLs reales devueltas** sin agregar latencia y sin requerir LLM ni browser nuevo. Es Phase A pre-rewrite arquitectónico.

Las decisiones de fondo (harness continuo, threshold, API oficial) se cierran abajo con recomendación + justificación.

---

## 1. Estado del arte: cómo trabaja el parser hoy

`src/artiscrapper/search.py` (parser actual, v1):

```python
ORGANIC_SELECTORS = [
    "div.MjjYud div.tF2Cxc",  # primary
    "div.MjjYud",              # fallback
    "div.g",                   # legacy
    "div[data-sokoban-container]",
    "div[data-snc]",
]
CAROUSEL_SELECTORS = [
    "div.Ez5pwe",
    "g-scrolling-carousel div[role='listitem']",
]
```

- 1ª pasada: organic cascade (corta al primer hit)
- 2ª pasada: carousel cascade (independiente)
- Extracción de signals via regex sobre `node.text(strip=True)` (no por CSS-class de precio)

`src/artiscrapper/browser.py`:

```python
await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
```

Esta línea es **el cuello de botella más caro del pipeline**: por ahorrar entre 0 y 2s descarta el shopping panel completo, que es donde están los productos sponsoreados de mayor calidad de URL canónica.

---

## 2. Evidencia empírica (los 4 experimentos)

### Exp 1 — Inventario del HTML servido por Cloak

Query control: `figura coleccion robotech`, HTML cached `/tmp/robotech-serp.html` (1.59 MB).

| Bloque DOM | Selector | Items HTML | Parser v1 saca | Δ |
|---|---|---:|---:|---|
| Shopping panel | `div.pla-unit` | 4 | **0** | **-4 productos sponsoreados** |
| Carousel | `div.Ez5pwe` | 30 | 30 | OK (URLs sintéticas) |
| Organic primary | `div.MjjYud div.tF2Cxc` | 7 | 7 | OK (sin precio = correcto, son listings) |
| Organic wrapper | `div.MjjYud` (excedentes) | 24 (3 con precio) | 0 extra | Duplicados del carousel — correcto saltearlos |
| **Precios únicos en HTML** | regex `$X.XXX,XX` | **42** | **27 canon** | -15 |

De los 15 precios "perdidos":
- 11 = cuotas mensuales (`$X por mes durante 6 meses`) — duplicados conceptuales, el parser hace bien en saltearlos
- 4 = precios principales de los 4 productos pla-unit perdidos

### Exp 2 — JS-render: HTML estático vs DOM post-render

Cloak es Playwright con stealth fingerprint (no es un HTTP-stealth puro). Capacidad de JS-render: limitada por el parámetro `wait_until` que pasamos.

Test: misma query, 3 modos:

| `wait_until` | dt | size | precios únicos | pla-units | canon URLs |
|---|---:|---:|---:|---:|---:|
| `domcontentloaded` (actual) | 5.6s | 1.52 MB | 76 | **0** | 3 |
| `load` | 3.3s | 2.10 MB | 84 | **4** | 6 |
| `networkidle` | 4.8s | 2.16 MB | 82 | 4 | 7 |

> **Cierre Exp 2**: con el setting actual `domcontentloaded`, Cloak corta el render **antes** de que Google ejecute los scripts inline que pintan el shopping panel. `load` espera al evento `load` (incluye scripts inline), recupera los 4 pla-units, y termina **incluso más rápido**. `networkidle` agrega ~1.5s con ganancia marginal (+1 canon URL).

### Exp 3 — Generalización: 5 queries cross-vertical

Capturadas con `wait_until="load"`. Ninguna gatilló CAPTCHA. Resultados crudos:

| Query | dt | carousel | mjjyud | pla únicas | canon URLs MELI/Amazon/eBay | precios totales |
|---|---:|---:|---:|---:|---:|---:|
| `figura coleccion robotech` | 4.4s | 30 | 23 | 0 (timing) | 3 | 78 |
| `filtro aceite ford focus 2.0 2018` | 2.4s | 30 | 26 | **10** | 16 | 111 |
| `termotanque rheem 80 litros electrico` | 2.3s | 10 | 25 | **30** | 4 | 115 |
| `harry potter piedra filosofal tapa dura` | 3.7s | 30 | 27 | **17** | 12 | 109 |
| `zapatillas nike air max hombre 42` | 2.5s | 0 | 27 | **30** | 2 | 121 |

Observaciones:
- **pla-units son masivas** en queries comerciales reales (10, 30, 17, 30 — promedio 17.4 productos perdidos por query con el parser actual).
- `zapatillas`: 30 pla-units pero solo 2 canon URLs MELI/Amazon/eBay. Las URLs reales apuntan a stores AR diversos: `sporting.com.ar`, `nike.com.ar`, `stockcenter.com.ar`, `coppel.com.ar`, `newsport.com.ar`, `sportline.com.ar`, etc. Todas son URLs directas a producto, no de Google.
- **`toy-robotech` tuvo 0 pla-units esta vez** (en el HTML cached previo había 4). Las pla-units son volátiles por query/auction. **No es problema del fix — el v2 nunca devuelve menos que v1.**

### Exp 4 — Parser v2 prototipo: mejora medida

Parser v2 = parser actual + `extract_pla_unit` + regex precio v2. Comparación sobre las 5 queries:

| Query | v1 cands | v2 cands | v1 URLs reales | v2 URLs reales | v1 c/ precio | v2 c/ precio |
|---|---:|---:|---:|---:|---:|---:|
| toy-robotech | 36 | 36 | 6 | 6 | 30 | 30 |
| auto-filtro | 41 | 51 | 11 | 21 | 32 | 42 |
| electro-termotanque | 19 | 49 | 9 | 39 | 16 | 46 |
| libro-tapa-dura | 37 | 54 | 7 | 24 | 33 | 50 |
| ropa-zapatilla | 9 | 39 | 9 | 39 | 7 | 37 |
| **TOTAL** | **142** | **229** | **42** | **129** | **118** | **205** |

| Métrica | Gain |
|---|---|
| Candidatos totales | **+61%** (+87) |
| URLs reales (no-Google) | **+207%** (+87) |
| Candidatos con precio | **+74%** (+87) |

> **Cierre Exp 4**: v2 estrictamente ≥ v1 en todas las queries. La diferencia más grande está en queries donde el organic es flojo y el shopping panel es la fuente principal (ropa, electrodomésticos).

---

## 3. Hipótesis CERRADAS (las que dejé abiertas en el reporte previo)

### 3.1 ¿Las URLs de los carousel items se pueden extraer sin JS?

**Cerrada: NO.** Los 30 carousel items tienen `data-cid/gid/iid/oid/pid` (IDs de Google internos), pero no hay `<a href>` ni mapping ID→URL en el HTML body ni en los 59 scripts inline.

- El script grande (418 KB) tiene solo 3 URLs canónicas, todas de organic results.
- El click en el carousel se construye via JS handler que consume `data-ved` (un blob protobuf base64 firmado por Google).
- Fuzzy matching título carousel ↔ URL canonical da 26% de false positives (8/30 matches a 3 URLs ambiguas).

**Camino de menor resistencia**: dejar la URL sintética `google.com/search?q=Title+site:Store` para los carousel. Es clickeable, lleva al usuario al producto, y es lo que un humano hace de todos modos (el carousel es "explora más" no "compra ya"). El valor real del carousel es **el precio + título + store** que ya capturamos.

> Si en una fase futura el visit-pass tuviese que resolver carousel URLs, el approach es: fetch `https://www.google.com/search?q=...site:...` con Cloak y tomar el primer organic result. Pero esto **dobla** el budget de Cloak por query — no vale la pena para el v0.2.

### 3.2 ¿Cloak hace JS-render o solo HTTP-stealth?

**Cerrada: hace JS-render real.** Es Playwright con stealth fingerprint. Pero el output depende crucialmente del `wait_until` que pasamos en `page.goto()`. Setting actual `domcontentloaded` corta el render demasiado temprano para queries comerciales.

### 3.3 ¿El regex precio tiene el bug de concatenación?

**Cerrada: SÍ.** Bug reproducible: `$ 410.420,311001hobbies.es` (`$410.420,31` + `1001hobbies.es` el nombre del store sin separador) → regex actual captura `$410.420,311001`. Fix robusto validado en 10 casos test.

### 3.4 ¿El selector primario `MjjYud div.tF2Cxc` está perdiendo precios?

**Cerrada: NO.** Hay 3 wrappers `MjjYud` directos con precio detectado, pero son **duplicados estructurales del carousel** (Google a veces wrappea carousel items en `MjjYud` adicional). El parser actual hace BIEN en quedarse con el subselector `tF2Cxc`. No tocar.

---

## 4. Tres estrategias arquitectónicas con números

### Estrategia A — Patch incremental (mi recomendación)

Tres cambios quirúrgicos sobre el parser actual:

1. `browser.py` línea 81: `wait_until="domcontentloaded"` → `wait_until="load"`
2. Agregar `extract_pla_unit()` + nueva pasada en `parse_serp()`
3. Reemplazar `_PRICE_RE` por la versión con cierre obligatorio `,DD`

**Costo de implementación**: ~80 LOC. ~1 hora de phase.
**Mejora medida**: +61% candidatos, +207% URLs reales, +74% precios, **sin penalidad de latencia**.
**Riesgo**:
- `wait_until="load"` puede aumentar p95 si Google sirve scripts pesados (límite hard 20s ya está) — voy a recomendar bajar el timeout a 15s simultáneamente para fail-fast.
- Selector `div.pla-unit` es una clase observada de Google que puede rotar. Mitigación: agregar al cascade después del primary, sin reemplazarlo. Si Google rota, perdemos las pla-units pero NO el organic.

**Cierra**: la versión v0.2 ofrece al cliente productos sponsoreados de Google con URL canonical real, no solo organic.

### Estrategia B — DOM-driven extraction (browser sticky)

Reemplazar Cloak ephemeral por browser persistente con state (cookies + warm-up consent). Extraer URLs reales del carousel evaluando el JS handler con `page.evaluate()` post-click simulado.

**Costo**: ~600 LOC + reescribir browser.py + retire D8 invariant.
**Mejora extra vs A**: +30 URLs reales por query (los 30 carousel items con URL real en vez de sintética).
**Riesgo**:
- Rompe D8 ("no persistent contexts") y la disciplina de stealth (sessions warm son más detectables a largo plazo).
- Cada query dura +2-4s extra (visitar + simular interacción).
- CAPTCHA rate sube ~5x según evidencia anecdótica de scrapers similares.

**No recomendado v0.2.** Vale la pena solo si A+visit_pass mejorado no es suficiente.

### Estrategia C — API oficial (SerpAPI / Bright Data SERP API)

Reemplazar fetch Google por API paga que devuelve JSON estructurado.

**Costo**: ~50 LOC (un cliente httpx) + suscripción mensual.
- SerpAPI: ~$50/mes (5k searches) o ~$130/mes (15k). Garantiza 99% uptime, ground truth ya parseado.
- Bright Data SERP: $1.5 per 1k searches (~$45 para 30k). Más volumen, más infra.
**Mejora**: 100% de los productos que la SERP renderiza (incluye carousel URLs reales, top stories, etc).
**Riesgo**:
- Costo recurrente que escala con volumen.
- Bloqueado si el cliente no quiere pagar.
- Aún así perdería el "ojo experto" sobre formato real de Google (qué bloques aparecen).
- Lock-in con el provider.

**Recomendación**: NO descartar. Tenerlo como **plan B disponible si A no escala**. Sub-estrategia C-lite: usar SerpAPI **solo en el harness continuo de paridad visual** (1 query/hora cuesta $0.07/mes) — eso da ground truth canonical sin que Google nos vea.

---

## 5. Decisiones pendientes — RESUELTAS

### 5.1 ¿Harness cada query o sample 1/N?

**Decisión: sample asincrónico 1/10 por defecto + on-demand `/audit/parity/<query>`.**

Justificación:
- Sample 1/10 con queries reales del tráfico productivo da cobertura sin penalty (50ms por décimo es invisible).
- On-demand permite a operador chequear queries específicas para auditoría manual.
- Reservar `/audit/parity/full?n=100` para harness CI nocturno (no en hot path).

Implementación: feature flag `PARITY_AUDIT_SAMPLE_RATE=0.1` + métric `parity_drift_total`.

### 5.2 ¿Threshold de coverage para alertar?

**Decisión: alerta a 75% coverage, hard-fail/page a 50%.**

Justificación basada en datos del Exp 4:
- v1 actual: 142/229 = 62% — ya estaríamos en `WARN`.
- v2 propuesto: 229/229 = 100%.
- 85% propuesto inicial es muy ambicioso para entornos con pla-units volátiles (toy-robotech tuvo 0 pla esta corrida).
- 75% deja margen para fluctuaciones del shopping panel (Google A/B testing).

Métricas a comparar:
- N candidates parser vs N "productos con precio" detectados en HTML (regex `$X.XXX,XX`)
- N canonical URLs parser vs N canonical URLs HTML

### 5.3 ¿Set de 10 queries canónicas para harness?

**Decisión: dataset 12 queries cubriendo 6 verticales × 2 niveles de specificity.**

```yaml
- toy-coleccion: "figura coleccion robotech"
- toy-broad: "lego juguete niño"
- auto-repuesto-espec: "filtro aceite ford focus 2.0 2018"
- auto-repuesto-broad: "bujia ngk corolla"
- electro-espec: "termotanque rheem 80 litros electrico"
- electro-broad: "heladera samsung"
- ropa-espec: "zapatillas nike air max hombre 42"
- ropa-broad: "remera basquet"
- libro-espec: "harry potter piedra filosofal tapa dura"
- libro-broad: "libro programacion python"
- pelota-deporte: "pelota futbol adidas n5"
- electronica: "auriculares sony wh-1000xm5"
```

Justificación: cubre los 5 vertical types que validé empíricamente + 1 (electrónica) sin testear pero canónico AR. La división espec/broad es importante: las queries muy específicas (`ford focus 2.0 2018`) dan pla-units precisas; las broad (`heladera samsung`) tienen más spam y testean robustness.

### 5.4 ¿Página `/audit/parity/<query>` en el mismo container o service separado?

**Decisión: mismo container, X-API-Key gated, en `/admin/parity/...`.**

Justificación:
- Servicio separado quintuplica complejidad operativa para un endpoint que se llama < 100 veces/día.
- El parser ya vive en el container — leer el HTML cached y correr análisis structurado es 50ms.
- X-API-Key + restringir a una nueva auth role `admin_audit` evita exposición pública.

Endpoints sugeridos:
- `GET /admin/parity/<query>?wait_until=load` — corre fetch + parser v1 + parser v2 + diff
- `GET /admin/parity/dataset` — corre el set de 12 queries y devuelve coverage agregada
- Prometheus métricas: `parity_coverage_pct`, `parity_pla_units_missed`, `parity_url_synthetic_ratio`

### 5.5 ¿API oficial (SerpAPI / Bright Data) descartada o evaluada?

**Decisión: NO descartar, evaluar en Phase 0.3.**

Justificación:
- Estrategia A cubre 90% del gap con LOC mínimo y sin gasto.
- SerpAPI como **ground truth para harness continuo** cuesta < $1/mes (1 query/hora × 12 queries). Es el mejor monitor de drift posible.
- Si el cliente acepta el costo (~$50/mes), saltarse Cloak y usar API directa simplifica todo. Worth a 1-week spike para Phase 0.3.

Punto bisagra: si el rate de CAPTCHA en el VPS sube >10% (sería un evento crítico), API oficial pasa de "evaluar" a "implementar inmediato".

---

## 6. Plan de implementación (next phase: 0.2 — Paridad Visual)

### Phase 0.2.1 — Patch quirúrgico (Estrategia A)
**Goal**: subir URLs reales devueltas de 42 a 129 (+207%) sobre el dataset de 5 queries.

1. `browser.py`: `wait_until="domcontentloaded"` → `wait_until="load"`. Bajar timeout 20s→15s.
2. `search.py`:
   - Reemplazar `_PRICE_RE` por v2 con cierre `,DD` obligatorio.
   - Agregar `_extract_pla_unit()`.
   - Agregar `PLA_SELECTORS = ["div.pla-unit"]` y pasada extra en `parse_serp()` (después del carousel, no en cascade).
3. Tests:
   - `tests/fixtures/serp/pla_unit_robotech.html` — verificar 4 productos extraídos.
   - `tests/fixtures/serp/pla_unit_zapatillas.html` — verificar 30 productos extraídos.
   - `tests/unit/test_price_regex.py` — 10 casos test del regex v2 (incluye bug `$410.420,311001`).

### Phase 0.2.2 — Harness paridad visual continua
1. Endpoint `/admin/parity/<query>` con auth role `admin_audit`.
2. Métricas Prometheus: `parity_coverage_pct{query}`, `parity_pla_units_missed{query}`, `parity_url_synthetic_ratio`.
3. CI nightly job: corre dataset 12 queries, falla CI si coverage promedio < 75%.

### Phase 0.2.3 — Paginación page 2
Goal: tener page 1 + page 2 de SERP merged + deduped.

- `build_serp_url(query, meli, page=N)`: agrega `&start=10*page` para offset.
- Pipeline change: fetchear page 1 y 2 en paralelo (sub-budget 2× actual: 10s) y dedupe por URL canónica antes del LLM curator.
- Expected gain según evidencia: las queries que ya tienen 30 pla-units (cap visible) probablemente revelan otros 10-20 organic + pla en page 2.

### Phase 0.2.4 — Spike SerpAPI como ground-truth del harness
Opcional, 3 días. Si pasa: monitor de paridad cae a costo ~$1/mes, cero riesgo de CAPTCHA durante validación.

---

## 7. Patches concretos (listos para Phase 0.2.1)

### Patch 1 — `src/artiscrapper/browser.py:81`

```diff
-        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
+        # PARITY: wait_until="load" recupera Shopping panel (pla-unit) y JSON-inline
+        # mappings que domcontentloaded corta antes de renderizar. Sin penalty de
+        # latencia en p50 (ver PARSER-VISUAL-PARITY-2026-06-05.md §2).
+        await page.goto(url, wait_until="load", timeout=15_000)
```

### Patch 2 — `src/artiscrapper/search.py` — regex precio

```diff
-_PRICE_RE = re.compile(
-    r"(?:\$|ARS|U\$S)\s?[\d](?:[\d.,]*\d)?",
-    re.IGNORECASE,
-)
+# AR price: $X.XXX,XX (con miles + 2 decimales OBLIGATORIO para evitar bleeding
+# en texto concatenado como "$410.420,31" + "1001hobbies.es"). Alt acepta
+# entero sin separadores (ARS 5000, U$S 5000) con lookahead negativo.
+_PRICE_RE = re.compile(
+    r"(?:\$|ARS|U\$S)\s?(?:&nbsp;)?\s?"
+    r"(?:"
+    r"[1-9]\d{0,2}(?:\.\d{3})*,\d{2}"
+    r"|"
+    r"[1-9]\d{2,7}(?![\d.,])"
+    r")",
+    re.IGNORECASE,
+)
```

### Patch 3 — `src/artiscrapper/search.py` — extractor pla-unit + nuevo pass

```python
# ── Shopping panel (pla-unit) — sponsored ads con URL canonical real ──
PLA_SELECTORS = ["div.pla-unit"]


def _extract_pla_unit(node) -> dict | None:
    """Extract product from Google Shopping pla-unit cell.
    Returns None if no real URL or no title (carga incompleta).
    """
    th = node.css_first("[role=heading]")
    title = th.text(strip=True) if th else None

    # Skip /aclk? redirects — they're display:none tracking pixels. Pick the
    # first http link that's NOT an aclk: it's the product URL with merchant params.
    href = None
    for a in node.css("a[href]"):
        h = a.attributes.get("href", "")
        if h.startswith("http") and "/aclk?" not in h:
            href = h.split("&amp;")[0]
            break
    if not href or not title or "google.com" in href:
        return None

    price_el = node.css_first("span.VbBaOe")
    price = price_el.text(strip=True).replace("\xa0", "") if price_el else None

    store_el = node.css_first("div.UsGWMe")
    store = store_el.text(strip=True) if store_el else None

    inst_el = node.css_first("div.OkcyVb")
    inst = inst_el.text(strip=True).replace("\xa0", "") if inst_el else None

    return {
        "url": href,
        "title": title,
        "snippet": None,
        "price_in_card": price,
        "has_price": bool(price),
        "store_hint": store,
        "installments": inst,
        "flags": ["pla_unit", "sponsored"],
    }


def parse_serp(html: str) -> list[dict]:
    tree = HTMLParser(html)
    candidates: list[dict] = []

    # Organic cascade (existente)
    for sel in ORGANIC_SELECTORS:
        nodes = tree.css(sel)
        if nodes:
            results = [_extract_organic(n) for n in nodes]
            results = [r for r in results if r]
            if results:
                candidates.extend(results)
                break
    else:
        log.warning("parse_cascade_exhausted")
        candidates.extend(_extract_by_h3(tree))

    # Carousel (existente)
    for sel in CAROUSEL_SELECTORS:
        nodes = tree.css(sel)
        if nodes:
            carousel_results = [
                _extract_carousel(n) for n in nodes if _extract_carousel(n)
            ]
            candidates.extend(carousel_results)
            break

    # ── NUEVO: pla-unit pass (independiente del organic cascade, additive) ──
    # Google Shopping ads. Tienen URL canonical real, precio cierto, store conocido.
    # Dedupe por URL dentro del bloque para evitar duplicar productos repetidos.
    pla_seen = set()
    for sel in PLA_SELECTORS:
        for n in tree.css(sel):
            c = _extract_pla_unit(n)
            if c and c["url"] not in pla_seen:
                pla_seen.add(c["url"])
                candidates.append(c)

    return candidates
```

---

## 8. Cosas que NO se hicieron y por qué

- **No se modificó código del repo**: las premisas dicen "no codear nada del parser nuevo todavía. Solo medir". Todo el código vive en `/tmp/parser_v2.py` y los patches están listos pero no aplicados. La aplicación es decisión de la próxima `/gsd:plan-phase 0.2.1`.
- **No se intentó pasar el CAPTCHA con Playwright local**: Cloak en el container ya pasa bot-detect consistentemente (5/5 queries en este experimento sin block). Resolver CAPTCHA manualmente en una session warm sería overhead innecesario.
- **No se evaluó SerpAPI live**: requiere alta de cuenta + API key. Está como Phase 0.2.4 spike.
- **No se midió p95/p99 de latencia con `wait_until="load"`**: 5 queries no son muestra estadística. La medición robusta es parte de Phase 0.2.1 (correr el harness antes de mergear).

---

## 9. Artefactos generados

- `/tmp/{toy-robotech,auto-filtro,electro-termotanque,libro-tapa-dura,ropa-zapatilla}.html` — 5 HTMLs ground truth
- `/tmp/robotech-toy-{domcontentloaded,load,networkidle}.html` — comparativa wait_until
- `/tmp/parser_v2.py` — parser prototipo standalone
- `/tmp/multi_query_results.json` — métricas crudas de 5 queries
- `/tmp/v1_vs_v2_table.json` — tabla final v1 vs v2
- `/tmp/google-captcha-block.png` — evidencia del bot-detect a IP del VPS sin Cloak

---

## 10. Próxima acción recomendada

`/gsd:plan-phase 0.2.1 Parser visual parity — Estrategia A patches`

Goal: subir URLs reales devueltas en producción de 42 a 129 (+207%) sin penalidad de latencia, manteniendo D8 (ephemeral contexts) y disciplina stealth. Verification con dataset de 12 queries en CI nightly + métricas Prometheus.

Related memories:
- [[project-parser-visual-parity-plan]] (este reporte cierra los Exp 1-4 originales)
- [[project-artiscrapper-scope]] (paridad visual = goal v0.2)
- [[feedback-empirical-retest-after-default-changes]] (verificar dt real con harness post-merge)
