# Phase 0.2.1 — Parser Visual Parity (Estrategia A) — DRAFT

**Estado**: borrador generado por `/gsd-plan-phase 0.2.1` el 2026-06-05.
**Bloqueo formal**: el workflow GSD requiere `/gsd-new-milestone v0.2` ejecutado antes de planear phases. STATE.md está en `Awaiting next milestone`; ROADMAP.md no tiene phase 0.2.1 listada; no existe `.planning/REQUIREMENTS.md` para v0.2.

Sesión desatendida — no se modificó ROADMAP ni STATE para respetar tu control sobre el scope de v0.2. El reporte empírico que justifica esta phase está en `.planning/PARSER-VISUAL-PARITY-2026-06-05.md`.

## Contenido del draft

| Archivo | Equivalente formal | Función |
|---|---|---|
| `0.2.1-CONTEXT.md` | `<phase>-CONTEXT.md` | Decisiones lockeadas para esta phase, derivadas del reporte |
| `0.2.1-RESEARCH.md` | `<phase>-RESEARCH.md` | Apunta al reporte ya escrito + diff técnico |
| `0.2.1-01-PLAN.md` | Wave 1 — Parser core fixes (browser wait_until + regex precio + pla-unit extractor) |
| `0.2.1-02-PLAN.md` | Wave 2 — Tests + fixtures + harness paridad visual continua |

## Pasos para formalizar (cuando despiertes)

```bash
# 1. Inicia milestone v0.2 (decide scope + crea REQUIREMENTS.md + STATE.md flip)
/gsd-new-milestone v0.2

# 2. Inserta esta phase en el roadmap
/gsd-phase 0.2.1 "Parser Visual Parity — Estrategia A patches"

# 3. Mueve los artifacts a la ubicación canónica
mv .planning/drafts/0.2.1-parser-visual-parity \
   .planning/phases/0.2.1-parser-visual-parity

# 4. Si querés re-correr el flow formal completo (con plan-checker + nyquist):
/gsd-plan-phase 0.2.1 --skip-research   # ya tenés RESEARCH.md y CONTEXT.md
```

Alternativamente, podés saltarte el wrapper y ejecutar directo:

```bash
# Para arrancar los patches sin pasar por el plan-checker:
/gsd-execute-phase 0.2.1
```

## Por qué no escalé esto autónomamente

`/gsd-new-milestone` está hecho para que decidas:
- Qué triggers de la v0.2 cumple cada phase
- Prioridad relativa (¿parser parity va antes que Phase 4 production-ops? ¿después?)
- REQ-IDs canónicos del milestone

Crear esos artifacts por mi cuenta presupone tu juicio sobre scope. Phase 0.2.1 como **primera phase de v0.2** es la apuesta más razonable dado el ROI medido (+207% URLs reales), pero queda a vos confirmarlo.

Related: ver memoria `[[feedback-autonomous-overnight-mode]]` para el protocolo de modo desatendido.
