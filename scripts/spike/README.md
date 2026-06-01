# scripts/spike — artiscrapper Phase 1 Spike Scripts

Throwaway probe scripts for empirical validation. These are NOT production code.
Phase 2 will write the real `src/` layout.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_ROUTER_URL` | `http://127.0.0.1:3210` | Base URL of the local-llms-router. Override if spike runs on a different machine than the VPS. |
| `ROUTER_BEARER_TOKEN` | (read from `.env.spike`) | Bearer token for the router. NEVER commit to git — `.env.spike` is gitignored. |

### One-Time Token Extraction

Run once to create `.env.spike` (gitignored):

```bash
TOKEN="$(grep '^ROUTER_BEARER_TOKEN=' /home/luis/proyectos/local-llms/.env | cut -d= -f2-)"
test -n "$TOKEN" && echo "ROUTER_BEARER_TOKEN=$TOKEN" > /home/luis/proyectos/artiscrapper/.env.spike
chmod 600 /home/luis/proyectos/artiscrapper/.env.spike
echo "Done — .env.spike created (gitignored)"
```

All spike scripts that touch the router read `ROUTER_BEARER_TOKEN` from `.env.spike`.
If `.env.spike` is missing, scripts exit with code 2 and print a hint pointing at this README.

---

## Setup (one-time)

```bash
# Create venv and install spike-only deps
uv venv .venv && source .venv/bin/activate
uv pip install 'cloakbrowser==0.3.31' 'httpx[http2]==0.28.1' 'httpx-sse>=0.4.0' \
  'selectolax==0.4.10' 'pydantic>=2.0'

# Install Cloak's bundled Chromium binary
python -c "from cloakbrowser import install; install()"
# If the above fails, try: python -m cloakbrowser install
# Or: python -m playwright install chromium
```

---

## Run Order

Scripts are numbered to reflect the correct sequential run order.
**NEVER run in parallel** — concurrent Google fetches multiply IP-block risk.

| Script | Plan | Purpose |
|--------|------|---------|
| `01_verify_cloak_tag.sh` | 01-01 | Verify `cloakhq/cloakbrowser:0.3.31` exists on Docker Hub + GitHub chromium release tag (D1 gate) |
| `02_cloak_smoke.py` | 01-01 | Cold-boot smoke + pws=0 SERP fetch + cookie isolation between ephemeral contexts (D8 gate) |
| `03_pws_consent_probe.py` | 01-01 | Top-up SERP fixtures to 8-10; aggregate consent-interstitial marker stats (D3 gate) |
| `04_death_modes.sh` | 01-01 | SIGKILL / SIGSTOP / network-drop death-mode coverage; finalize SPIKE.md §Browser (D8 gate) |
| `05_router_probe.py` | 01-02 | Router /v1/models, TTFT, KV-cache, concurrency limit (D10 gate) |
| `09_label_cards.py` | 01-02 | Interactive labeller + validator for `tests/fixtures/llm/labelled.jsonl` (AC-5) |
| `06_capture_catalog.py` | 01-03 | Head-browse 10 AR catalog hosts, capture raw HTML to `tests/fixtures/catalog/` (AC-4) |
| `07_extract_fixture.py` | 01-03 | Run hand-rolled JSON-LD + OG + microdata extractor on each catalog fixture (D12 gate) |
| `08_falabella_403_rate.py` | 01-03 | httpx N=10 to Falabella PDP URLs; record 200/403 ratio (AC-6 Falabella row) |

Use `bash scripts/spike/run_all.sh` to run all scripts sequentially with banners.

---

## Exit Code Semantics

| Exit Code | Meaning |
|-----------|---------|
| 0 | Success — probe passed, all required artifacts produced |
| 2 | Missing env — `.env.spike` not found or required var empty; **re-run setup above** |
| Non-zero (other) | Empirical failure — record in SPIKE.md, do NOT retry blindly |

---

## Throttle Rules (per 01-RESEARCH.md §Anti-Patterns)

- **SERP fetches (Google):** ≤1 request/minute during `02_cloak_smoke.py` and `03_pws_consent_probe.py`. Spike uses `asyncio.sleep(60)` between queries.
- **Router probes:** ≤1 req/2s between probe sections in `05_router_probe.py`. 1 req/2s is sufficient (`queue_max_wait_ms=30000`).
- **Catalog visits:** ≥30s between same-host visits in `06_capture_catalog.py` and `08_falabella_403_rate.py`.
- **Aggregate SERP cap:** max 15 SERP fetches total across `02_cloak_smoke.py` + `03_pws_consent_probe.py`. Abort if 3 consecutive fetches hit `/sorry/index`.

---

## Anti-uvloop Reminder (D6)

Every Python spike script uses `asyncio.run(main())`. **NEVER use `uvloop.install()` or `uvloop.EventLoopPolicy()`.**
Cloak/Playwright's subprocess pipe protocol is incompatible with uvloop (D6 — PROJECT.md §Constraints).

---

## Security Notes

- `.env.spike` is gitignored. **Never `echo $ROUTER_BEARER_TOKEN` in committed script output.**
- `tests/fixtures/serp/*.html` may contain Google SERP HTML — never rendered in a browser context, only parsed via selectolax (T-01-01-02 + T-01-01-07 mitigations).
- Bearer token lives in `.env.spike` (chmod 600). Scripts read it at runtime; never log it.
