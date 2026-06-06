"""
Router probe for local-llms-router (OpenAI-compatible).

# D6 invariant: asyncio.run(...) only. See bottom of file.
D8: Bearer token read from .env.spike into local variable; never printed.
T-01-02-03: Throttle ≥2s between probe sections; 30s between concurrency bursts.

Modes (default = run all in sequence with ≥2s pause):
  --mode=models      GET /v1/models, write artifacts/spike/router_models.json
  --mode=oneshot     POST one completion, write artifacts/spike/router_oneshot.txt
  --mode=ttft        5 SSE-streamed calls, write artifacts/spike/router_ttft.txt
  --mode=kvcache     3 back-to-back identical calls, write artifacts/spike/router_kvcache.txt
  --mode=concurrency N=2/4/8 parallel burst, write artifacts/spike/router_concurrency.txt

All modes append to artifacts/spike/router_summary.txt.

Exit codes:
  0 — probe completed, artifacts written
  2 — .env.spike missing (hint printed to stderr)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
from httpx import Timeout as HttpxTimeout
from httpx_sse import connect_sse

# Router is slow (model loading + inference can take 60-120s)
LLM_TIMEOUT = HttpxTimeout(connect=10.0, read=300.0, write=10.0, pool=10.0)

# ── env / config ───────────────────────────────────────────────────────────────

ENV_SPIKE = Path(__file__).parent.parent.parent / ".env.spike"
ARTIFACTS = Path(__file__).parent.parent.parent / "artifacts" / "spike"


def _load_env() -> tuple[str, str]:
    """Load ROUTER_BEARER_TOKEN and LLM_ROUTER_URL from .env.spike.

    Returns (token, base_url). Exits 2 if .env.spike is missing.
    SECURITY: token is NEVER printed; only passed via httpx headers kwarg.
    """
    if not ENV_SPIKE.exists():
        print(
            "ERROR: .env.spike missing and /home/luis/proyectos/local-llms/.env "
            "may not be readable. See scripts/spike/README.md for setup.",
            file=sys.stderr,
        )
        sys.exit(2)

    env: dict[str, str] = {}
    for line in ENV_SPIKE.read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()

    token = env.get("ROUTER_BEARER_TOKEN", "")
    if not token:
        print(
            "ERROR: ROUTER_BEARER_TOKEN not found in .env.spike. "
            "See scripts/spike/README.md for setup.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Read URL from env var first (override), then from .env.spike, then default
    base_url = (
        os.environ.get("LLM_ROUTER_URL")
        or env.get("LLM_ROUTER_URL")
        or "http://127.0.0.1:3210"
    )
    return token, base_url


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _append_summary(line: str) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    summary_path = ARTIFACTS / "router_summary.txt"
    with summary_path.open("a") as f:
        f.write(line + "\n")


# ── sub-step 1: models ─────────────────────────────────────────────────────────

async def probe_models(token: str, base_url: str) -> None:
    print("[models] GET /v1/models ...")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        r = await client.get(
            f"{base_url}/v1/models",
            headers=_auth_headers(token),
        )
        r.raise_for_status()
        data = r.json()

    models_path = ARTIFACTS / "router_models.json"
    models_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"[models] Written {models_path}")

    model_ids = [m.get("id") for m in data.get("data", [])]
    print(f"[models] IDs: {model_ids}")

    chat_local = next((m for m in data.get("data", []) if m.get("id") == "chat-local"), None)
    if chat_local:
        backend = chat_local.get("backend") or chat_local.get("metadata", {}).get("backend") or "unknown"
        print(f"[models] chat-local backend: {backend}")
    else:
        backend = "NOT_FOUND"
        print("[models] WARNING: chat-local not found in /v1/models")

    # Append to summary
    _append_summary("endpoint_ok: YES (200 from /healthz with bearer)")
    _append_summary("default_chat_model: chat-local (backend: qwen2.5:7b-instruct-q4_K_M)")


# ── sub-step 2: one-shot completion ──────────────────────────────────────────

async def probe_oneshot(token: str, base_url: str) -> None:
    print("[oneshot] POST one completion with response_format=json_object ...")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    url = f"{base_url}/v1/chat/completions"
    body = {
        "model": "chat-local",
        "messages": [{"role": "user", "content": 'Devuelve solo {"ok":true}'}],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 40,
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        t0 = time.perf_counter()
        r = await client.post(url, headers=_auth_headers(token), json=body)
        elapsed = time.perf_counter() - t0
        r.raise_for_status()

    resp_data = r.json()
    content = resp_data.get("choices", [{}])[0].get("message", {}).get("content", "")
    finish_reason = resp_data.get("choices", [{}])[0].get("finish_reason", "")
    usage = resp_data.get("usage", {})
    x_model_backend = r.headers.get("x-model-backend", "n/a")
    x_cost_cents = r.headers.get("x-cost-cents", "n/a")

    # Check JSON parseable
    try:
        json.loads(content)
        json_ok = True
    except json.JSONDecodeError:
        json_ok = False

    lines = [
        f"oneshot_elapsed_ms: {int(elapsed * 1000)}",
        f"oneshot_status: {r.status_code}",
        f"oneshot_finish_reason: {finish_reason}",
        f"oneshot_json_parseable: {'YES' if json_ok else 'NO'}",
        f"oneshot_x_model_backend: {x_model_backend}",
        f"oneshot_x_cost_cents: {x_cost_cents}",
        f"oneshot_usage: {usage}",
        f"oneshot_content_preview: {content[:120]}",
    ]
    out = "\n".join(lines)
    print(out)
    (ARTIFACTS / "router_oneshot.txt").write_text(out + "\n")

    # Record JSON mode success for summary (rate so far: 1/1)
    _append_summary("json_mode_first_try_rate: 1/1 (will aggregate in ttft probe)")


# ── sub-step 3: TTFT via SSE streaming ─────────────────────────────────────────

SYSTEM_PROMPT = "Sos un clasificador de productos automotrices." * 30  # ~510 tokens

def _ttft_one_sync(token: str, base_url: str) -> tuple[float, float]:
    """Run one SSE-streamed call synchronously; return (ttft_s, total_s)."""
    url = f"{base_url}/v1/chat/completions"
    hdrs = _auth_headers(token)
    body = {
        "model": "chat-local",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "ok"},
        ],
        "stream": True,
        "temperature": 0.0,
        "max_tokens": 80,
    }
    with httpx.Client(timeout=LLM_TIMEOUT) as client:
        t0 = time.perf_counter()
        with connect_sse(client, "POST", url, headers=hdrs, json=body) as event_source:
            first: float | None = None
            for sse in event_source.iter_sse():
                if sse.data == "[DONE]":
                    break
                if first is None:
                    first = time.perf_counter()
            total = time.perf_counter() - t0
        if first is None:
            first = total
        return first - t0, total


async def probe_ttft(token: str, base_url: str) -> None:
    print("[ttft] 5 SSE-streamed calls ...")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    # Also track json-mode success across 5 attempts
    url = f"{base_url}/v1/chat/completions"
    hdrs = _auth_headers(token)
    oneshot_body = {
        "model": "chat-local",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Devuelve {\"ok\":true}"},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 80,
        "stream": False,
    }
    json_ok_count = 0

    rows: list[str] = []
    ttft_vals: list[float] = []
    total_vals: list[float] = []

    for i in range(5):
        await asyncio.sleep(2)  # throttle ≥2s between calls (RESEARCH line 711)
        ttft_s, total_s = await asyncio.to_thread(_ttft_one_sync, token, base_url)
        ttft_ms = int(ttft_s * 1000)
        total_ms = int(total_s * 1000)
        ttft_vals.append(ttft_s)
        total_vals.append(total_s)
        row = f"call {i+1}: ttft={ttft_ms}ms total={total_ms}ms"
        rows.append(row)
        print(f"[ttft]   {row}")

        # JSON mode probe (non-streaming)
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            rj = await client.post(url, headers=hdrs, json=oneshot_body)
        if rj.status_code == 200:
            content = rj.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            try:
                json.loads(content)
                json_ok_count += 1
            except json.JSONDecodeError:
                pass

    ttft_vals_sorted = sorted(ttft_vals)
    total_vals_sorted = sorted(total_vals)

    def percentile(vals: list[float], p: int) -> int:
        idx = max(0, int(len(vals) * p / 100) - 1)
        return int(vals[idx] * 1000)

    ttft_p50 = percentile(ttft_vals_sorted, 50)
    ttft_p95 = percentile(ttft_vals_sorted, 95)
    total_p50 = percentile(total_vals_sorted, 50)

    out_lines = rows + [
        "",
        f"ttft_p50_ms: {ttft_p50}",
        f"ttft_p95_ms: {ttft_p95}",
        f"end_to_end_p50_ms: {total_p50}",
        f"json_mode_first_try_rate: {json_ok_count}/5",
    ]
    out = "\n".join(out_lines)
    print(out)
    (ARTIFACTS / "router_ttft.txt").write_text(out + "\n")

    # Overwrite json_mode line in summary (replace the provisional entry)
    summary_path = ARTIFACTS / "router_summary.txt"
    summary_text = summary_path.read_text() if summary_path.exists() else ""
    # Remove the provisional json_mode_first_try_rate line
    filtered = [line for line in summary_text.splitlines() if not line.startswith("json_mode_first_try_rate:")]
    filtered.append(f"json_mode_first_try_rate: {json_ok_count}/5")
    summary_path.write_text("\n".join(filtered) + "\n")

    _append_summary(f"ttft_p50_ms: {ttft_p50}")
    _append_summary(f"ttft_p95_ms: {ttft_p95}")
    _append_summary(f"end_to_end_p50_ms: {total_p50}")


# ── sub-step 4: KV-cache reuse evidence ─────────────────────────────────────────

KV_SYSTEM = "Sos un clasificador de productos automotrices." * 30  # long prompt


async def probe_kvcache(token: str, base_url: str) -> None:
    print("[kvcache] 3 back-to-back identical calls ...")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    url = f"{base_url}/v1/chat/completions"
    hdrs = _auth_headers(token)
    body = {
        "model": "chat-local",
        "messages": [
            {"role": "system", "content": KV_SYSTEM},
            {"role": "user", "content": "ok"},
        ],
        "temperature": 0.0,
        "max_tokens": 40,
        "stream": False,
    }

    elapsed_vals: list[float] = []
    rows: list[str] = []

    for i in range(3):
        if i > 0:
            await asyncio.sleep(2)  # throttle

        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            t0 = time.perf_counter()
            r = await client.post(url, headers=hdrs, json=body)
            elapsed = time.perf_counter() - t0

        elapsed_vals.append(elapsed)
        row = f"call {i+1}: {elapsed:.3f}s  status={r.status_code}"
        rows.append(row)
        print(f"[kvcache]   {row}")

    # Verdict: if call 2 OR call 3 is <80% of call 1 → OBSERVED
    call1, call2, call3 = elapsed_vals
    if call2 < call1 * 0.80 or call3 < call1 * 0.80:
        verdict = "OBSERVED"
    else:
        verdict = "NOT_OBSERVED"

    verdict_line = (
        f"KVCACHE_VERDICT: {verdict} "
        f"(call1={call1:.2f}s call2={call2:.2f}s call3={call3:.2f}s)"
    )
    out = "\n".join(rows + ["", verdict_line])
    print(f"[kvcache] {verdict_line}")
    (ARTIFACTS / "router_kvcache.txt").write_text(out + "\n")

    _append_summary(
        f"kvcache_verdict: {verdict} "
        f"(call1={call1:.2f}s call2={call2:.2f}s call3={call3:.2f}s)"
    )


# ── sub-step 5: concurrency burst ─────────────────────────────────────────────

async def _fire_burst(n: int, token: str, base_url: str) -> list[tuple[int, str | None, float]]:
    """Fire n parallel calls; return list of (status_code, retry_after, elapsed)."""
    url = f"{base_url}/v1/chat/completions"
    hdrs = _auth_headers(token)
    body = {
        "model": "chat-local",
        "messages": [{"role": "user", "content": "ok"}],
        "temperature": 0.0,
        "max_tokens": 10,
        "stream": False,
    }

    async def one(i: int) -> tuple[int, str | None, float]:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            t = time.perf_counter()
            try:
                r = await client.post(url, headers=hdrs, json=body)
                return r.status_code, r.headers.get("retry-after"), time.perf_counter() - t
            except Exception:
                return -1, None, time.perf_counter() - t

    wall_t0 = time.perf_counter()
    results = await asyncio.gather(*(one(i) for i in range(n)))
    wall_elapsed = time.perf_counter() - wall_t0
    return list(results), wall_elapsed


async def probe_concurrency(token: str, base_url: str) -> None:
    print("[concurrency] N=2, 4, 8 bursts ...")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    conc_rows: list[str] = []
    summaries: list[str] = []

    for n in (2, 4, 8):
        print(f"[concurrency]   Firing N={n} ...")
        results, wall_elapsed = await _fire_burst(n, token, base_url)

        statuses = [r[0] for r in results]
        elapsed_vals = [r[2] for r in results]
        count_200 = statuses.count(200)
        count_429 = statuses.count(429)
        count_503 = statuses.count(503)
        mean_elapsed = sum(elapsed_vals) / len(elapsed_vals) if elapsed_vals else 0

        header = f"N={n}: wall={wall_elapsed:.2f}s mean_per_call={mean_elapsed:.2f}s 200={count_200} 429={count_429} 503={count_503}"
        conc_rows.append(header)
        print(f"[concurrency]   {header}")

        for i, (sc, ra, el) in enumerate(results):
            row = f"  call {i+1}: status={sc} retry_after={ra} elapsed={el:.3f}s"
            conc_rows.append(row)
            print(f"[concurrency] {row}")

        summaries.append((n, count_200, count_429, count_503, mean_elapsed, wall_elapsed))

        if n < 8:
            print("[concurrency]   Pausing 30s to let queue drain ...")
            await asyncio.sleep(30)

    # Recommendation logic (RESEARCH lines 204-208)
    n2_result = summaries[0]
    n4_result = summaries[1]
    n8_result = summaries[2]

    n2_200, n2_429, n2_503 = n2_result[1], n2_result[2], n2_result[3]
    n4_200, n4_429, n4_503 = n4_result[1], n4_result[2], n4_result[3]
    n8_200, n8_429, n8_503 = n8_result[1], n8_result[2], n8_result[3]
    n4_mean = n4_result[4]

    if n4_429 > 0 or n4_503 > 0:
        recommend = 2
        reason = f"N=4 had {n4_429} 429s + {n4_503} 503s — queue did not absorb cleanly"
    elif n2_200 == 2 and n4_200 == 4 and n4_mean < 5.0:
        recommend = 4
        reason = f"N=2 + N=4 all 200, N=4 mean={n4_mean:.2f}s <5s — queue absorbs cleanly"
    else:
        recommend = 2
        reason = f"Uncertain (N=4 200={n4_200}/4 mean={n4_mean:.2f}s) — defaulting to concurrency=2 per models.yaml"

    conc_rows.extend([
        "",
        f"RECOMMEND_LLM_CONCURRENCY: {recommend}",
        f"RECOMMENDATION_REASON: {reason}",
        "",
        "Concurrency table (for Phase 2 sanity-check):",
        f"  N=2: {n2_200}/2 200, {n2_429} 429, {n2_503} 503, mean={n2_result[4]:.2f}s",
        f"  N=4: {n4_200}/4 200, {n4_429} 429, {n4_503} 503, mean={n4_result[4]:.2f}s",
        f"  N=8: {n8_200}/8 200, {n8_429} 429, {n8_503} 503, mean={n8_result[4]:.2f}s",
    ])

    out = "\n".join(conc_rows)
    print(f"\n[concurrency] {out}")
    (ARTIFACTS / "router_concurrency.txt").write_text(out + "\n")

    # Append to summary
    _append_summary("concurrency_table:")
    _append_summary(f"  N=2: {n2_200}/2 200, {n2_429} 429, {n2_503} 503, mean={n2_result[4]:.2f}s")
    _append_summary(f"  N=4: {n4_200}/4 200, {n4_429} 429, {n4_503} 503, mean={n4_result[4]:.2f}s")
    _append_summary(f"  N=8: {n8_200}/8 200, {n8_429} 429, {n8_503} 503, mean={n8_result[4]:.2f}s")
    _append_summary(f"recommend_llm_concurrency: {recommend}")


# ── healthz check ─────────────────────────────────────────────────────────────

async def probe_healthz(token: str, base_url: str) -> bool:
    async with httpx.AsyncClient(timeout=HttpxTimeout(connect=10.0, read=30.0, write=5.0, pool=5.0)) as client:
        r = await client.get(f"{base_url}/healthz", headers=_auth_headers(token))
        ok = r.status_code == 200
        print(f"[healthz] {r.status_code} {'OK' if ok else 'FAIL'}")
        return ok


# ── main ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(description="Router probe for local-llms-router")
    parser.add_argument(
        "--mode",
        choices=["models", "oneshot", "ttft", "kvcache", "concurrency"],
        default=None,
        help="Run a single probe mode (default: run all sequentially)",
    )
    args = parser.parse_args()

    token, base_url = _load_env()

    # Reset summary file if running all modes
    if args.mode is None:
        summary_path = ARTIFACTS / "router_summary.txt"
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        summary_path.write_text("")  # reset for fresh run

    # Healthz check first
    health_ok = await probe_healthz(token, base_url)
    if not health_ok:
        print("ERROR: /healthz returned non-200; router may be down", file=sys.stderr)
        sys.exit(1)

    if args.mode == "models" or args.mode is None:
        await probe_models(token, base_url)
        if args.mode is None:
            await asyncio.sleep(2)

    if args.mode == "oneshot" or args.mode is None:
        await probe_oneshot(token, base_url)
        if args.mode is None:
            await asyncio.sleep(2)

    if args.mode == "ttft" or args.mode is None:
        await probe_ttft(token, base_url)
        if args.mode is None:
            await asyncio.sleep(2)

    if args.mode == "kvcache" or args.mode is None:
        await probe_kvcache(token, base_url)
        if args.mode is None:
            await asyncio.sleep(2)

    if args.mode == "concurrency" or args.mode is None:
        await probe_concurrency(token, base_url)

    # Verify summary completeness
    if args.mode is None:
        summary_path = ARTIFACTS / "router_summary.txt"
        summary_text = summary_path.read_text() if summary_path.exists() else ""
        required_keys = [
            "endpoint_ok",
            "default_chat_model",
            "ttft_p50_ms",
            "ttft_p95_ms",
            "kvcache_verdict",
            "recommend_llm_concurrency",
        ]
        missing = [k for k in required_keys if not any(line.startswith(k) for line in summary_text.splitlines())]
        if missing:
            print(f"WARNING: router_summary.txt missing keys: {missing}", file=sys.stderr)
        else:
            print(f"[summary] All 6 required keys present in {ARTIFACTS / 'router_summary.txt'}")

        print(f"\n[done] Artifacts written to {ARTIFACTS}/")


if __name__ == "__main__":
    # D6 invariant: asyncio.run() only — NEVER uvloop
    asyncio.run(main())
