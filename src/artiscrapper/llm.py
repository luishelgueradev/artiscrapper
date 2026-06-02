"""
LLM curator module.
LLM-01..08 requirements.
Pattern 5 from 02-RESEARCH.md (lines 774-937) — verbatim.
SPIKE.md §LLM: POST /v1/chat/completions (OpenAI-compat), choices[0].message.content, json mode.
D2 FOOT-GUN: LLMVerdict.fallback() confidence=0.3 IS dropped at the <0.4 cut in should_keep().
LLM-08/OBS-05: NEVER log prompt content, response content, bearer_token, candidate fields.
LLM-03: module-level asyncio.Semaphore(LLM_CONCURRENCY=4) in curate_candidates.
"""

import asyncio
import json
from typing import Literal

import httpx
import structlog
from pydantic import BaseModel, Field, ValidationError

from .config import settings
from .metrics import metrics

log = structlog.get_logger()

FreshnessSignal = Literal["live_marketplace", "static_catalog", "blog", "unknown"]


class LLMVerdict(BaseModel):
    is_product: bool
    confidence: float = Field(ge=0.0, le=1.0)
    price_hint: float | None = None
    store_hint: str | None = Field(default=None, max_length=80)
    freshness_signal: FreshnessSignal
    reason: str = Field(max_length=140)

    @classmethod
    def fallback(cls, reason: str) -> "LLMVerdict":
        """
        Permissive fallback for LLM failure.
        CRITICAL D2 FOOT-GUN: confidence=0.3 is BELOW the <0.4 cut.
        A candidate with ONLY this fallback verdict IS DROPPED at the cutoff.
        'Permissive' means we don't raise an exception, NOT that we keep the candidate.
        """
        return cls(
            is_product=True,
            confidence=0.3,  # D2: confidence=0.3 is BELOW the <0.4 cut — this verdict IS dropped in should_keep()
            price_hint=None,
            store_hint=None,
            freshness_signal="unknown",
            reason=f"llm_fail:{reason}",
        )


SYSTEM_PROMPT = """Sos un clasificador de resultados de búsqueda de Google para una casa de repuestos automotores en Argentina.

Tu tarea: dado un resultado de búsqueda (título + URL + snippet), decidir si es un PRODUCTO COMPRABLE concreto o ruido (blog, foro, Wikipedia, YouTube, noticia, página institucional).

Respondé ÚNICAMENTE con un objeto JSON válido con este esquema exacto:
{
  "is_product": bool,
  "confidence": float,
  "price_hint": float|null,
  "store_hint": string|null,
  "freshness_signal": string,
  "reason": string
}

Reglas:
- Mercadolibre, Mercado Libre, MELI → freshness_signal="live_marketplace"
- Tienda con catálogo propio → "static_catalog"
- Blog, foro, YouTube, Reddit, Wikipedia, Fandom, noticia → "blog" (is_product=false)
- Si no podés decidir → "unknown" con confidence baja (≤0.4)
- NO inventes precios. Si no ves el número en el snippet, price_hint=null.
- NO inventes tiendas. Si la URL no es clara, store_hint=null.
- reason: máximo 80 caracteres en español

Devolvé sólo el JSON, sin markdown, sin explicaciones extras."""

FEW_SHOT_EXAMPLES = """
Ejemplo 1 — INPUT:
{"title":"Filtro Aceite Mahle Ford Focus 1.6 - $ 8.500","url":"https://www.mercadolibre.com.ar/MLA-12345","snippet":"Envío gratis. Stock disponible. Vendedor con +1000 ventas."}
OUTPUT:
{"is_product":true,"confidence":0.95,"price_hint":8500.0,"store_hint":"Mercadolibre","freshness_signal":"live_marketplace","reason":"Card MELI con precio y stock"}

Ejemplo 2 — INPUT:
{"title":"Cómo cambiar el filtro de aceite paso a paso","url":"https://taller-mecanico-blog.com/cambio-filtro","snippet":"Guía completa con fotos para hacer el mantenimiento vos mismo..."}
OUTPUT:
{"is_product":false,"confidence":0.97,"price_hint":null,"store_hint":null,"freshness_signal":"blog","reason":"Tutorial, no producto"}
"""

USER_TEMPLATE = "INPUT:\n{candidate_json}\nOUTPUT:"


async def classify_candidate(
    client: httpx.AsyncClient,
    candidate: dict,
    sem: asyncio.Semaphore,
    router_url: str,
    bearer_token: str,
) -> "LLMVerdict":
    """
    Classify a single SERP candidate via the local LLM router.
    LLM-01: per-candidate call to local-llms-router.
    LLM-07: temperature=0.0, max_tokens=128, json mode.
    LLM-08/OBS-05: NEVER log prompt, response content, bearer_token, or candidate fields.
    """
    async with sem:
        payload = {
            "model": settings.LLM_MODEL,  # configurable via env (LLM_MODEL); see config.py
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT + FEW_SHOT_EXAMPLES,
                    # KV-cache: constant system prompt across all calls
                },
                {
                    "role": "user",
                    "content": USER_TEMPLATE.format(
                        candidate_json=json.dumps(
                            {k: candidate.get(k) for k in ("title", "url", "snippet")},
                            ensure_ascii=False,
                        )
                    ),
                },
            ],
            "response_format": {"type": "json_object"},  # OpenAI-compat JSON mode
            "temperature": 0.0,
            "max_tokens": 128,
            "stream": False,
        }
        try:
            resp = await client.post(
                f"{router_url}/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {bearer_token}"},
                timeout=5.0,
            )
            resp.raise_for_status()
            # OpenAI-compat shape: choices[0].message.content — NOT message.content (Pitfall 5)
            raw = resp.json()["choices"][0]["message"]["content"]
            return LLMVerdict.model_validate_json(raw)
        except httpx.TimeoutException:
            metrics.llm_fallback_total["timeout"] += 1  # OBS-06
            return LLMVerdict.fallback("timeout")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 503:
                # LLM queue full — single retry after 1s (LLM-04)
                await asyncio.sleep(1.0)
                try:
                    resp2 = await client.post(
                        f"{router_url}/v1/chat/completions",
                        json=payload,
                        headers={"Authorization": f"Bearer {bearer_token}"},
                        timeout=5.0,
                    )
                    resp2.raise_for_status()
                    raw2 = resp2.json()["choices"][0]["message"]["content"]
                    return LLMVerdict.model_validate_json(raw2)
                except Exception:
                    metrics.llm_fallback_total["overload"] += 1  # OBS-06
                    return LLMVerdict.fallback("overload")
            metrics.llm_fallback_total[f"http_{e.response.status_code}"] += 1  # OBS-06
            return LLMVerdict.fallback(f"http_{e.response.status_code}")
        except (json.JSONDecodeError, ValidationError, KeyError):
            metrics.llm_fallback_total["malformed"] += 1  # OBS-06
            return LLMVerdict.fallback("malformed")
        except Exception:
            metrics.llm_fallback_total["conn_error"] += 1  # OBS-06
            return LLMVerdict.fallback("conn_error")


def should_keep(verdict: "LLMVerdict") -> bool:
    """
    D2 FOOT-GUN: confidence=0.3 fallback IS dropped here. This is intentional.
    The constant 0.4 is hard-coded — NOT configurable via env vars or settings.
    """
    if not verdict.is_product:
        return False
    if verdict.confidence < 0.4:  # D2: 0.3 < 0.4 → DROPPED (fallback always dropped)
        return False
    if verdict.freshness_signal == "blog":
        return False
    return True


async def router_health_check(router_url: str, bearer_token: str) -> bool:
    """
    LLM-06: check if router is healthy before attempting classification.
    Uses HEAD /healthz (with z, per SPIKE.md §LLM).
    Returns True if healthy, False if unreachable or erroring.
    LLM-08: bearer_token is NEVER logged.
    """
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.head(
                f"{router_url}/healthz",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            return r.status_code < 500
    except Exception:
        return False


async def curate_candidates(
    candidates: list[dict],
    router_url: str,
    bearer_token: str,
    concurrency: int = 4,
) -> tuple[list[dict], int, bool]:
    """
    LLM-03: classify all candidates with Semaphore(concurrency=4).
    LLM-05: drops confidence<0.4 (D2) or freshness_signal="blog".
    Returns (kept_candidates, dropped_count, llm_degraded).
    llm_degraded=True when >50% of candidates returned fallback verdicts.
    LLM-08: bearer_token is NEVER logged.
    """
    sem = asyncio.Semaphore(concurrency)
    fallback_count = 0
    kept: list[dict] = []
    dropped_count = 0

    async with httpx.AsyncClient(http2=True) as client:
        verdicts = await asyncio.gather(
            *[classify_candidate(client, c, sem, router_url, bearer_token) for c in candidates]
        )

    for candidate, verdict in zip(candidates, verdicts):
        # Track fallback for degraded mode detection (LLM-05)
        if verdict.reason.startswith("llm_fail:"):
            fallback_count += 1

        if should_keep(verdict):
            candidate["llm_confidence"] = verdict.confidence
            candidate["freshness_signal"] = verdict.freshness_signal
            if verdict.price_hint is not None:
                candidate.setdefault("price_hint", verdict.price_hint)
            kept.append(candidate)
        else:
            dropped_count += 1
            log.debug(
                "candidate_dropped",
                # OBS-05: only safe fields logged — no title/snippet/url/reason
                is_product=verdict.is_product,
                confidence=round(verdict.confidence, 2),
                freshness_signal=verdict.freshness_signal,
            )

    total = len(candidates)
    llm_degraded = total > 0 and fallback_count > total * 0.5

    return kept, dropped_count, llm_degraded
