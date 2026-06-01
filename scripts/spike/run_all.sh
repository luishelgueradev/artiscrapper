#!/usr/bin/env bash
# run_all.sh — Sequential orchestrator for all Phase 1 spike scripts.
# Per 01-RESEARCH.md §Anti-Patterns line 712: NEVER run spikes in parallel.
# Each script runs to completion (or failure) before the next starts.
# A failure is RECORDED, not aborted — the spike's job is to measure empirical reality.
#
# Usage: bash scripts/spike/run_all.sh [--plan 01-01 | 01-02 | 01-03]
#   No argument: runs all 9 scripts in order.
#   --plan 01-01: runs scripts 01-04 (browser spike only).
#   --plan 01-02: runs scripts 05, 09 (LLM spike).
#   --plan 01-03: runs scripts 06-08 (visit spike).
set -uo pipefail

PLAN_FILTER="${1:-all}"
if [ "$PLAN_FILTER" = "--plan" ]; then
    PLAN_FILTER="${2:-all}"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Source .env.spike if present — provides ROUTER_BEARER_TOKEN and LLM_ROUTER_URL.
ENV_FILE="$REPO_ROOT/.env.spike"
if [ -f "$ENV_FILE" ]; then
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    echo "[run_all] Loaded $ENV_FILE"
else
    echo "ERROR: $ENV_FILE missing — see scripts/spike/README.md for setup." >&2
    echo "       The LLM scripts (05, 09) will exit 2. Browser scripts (01-04) do not need it." >&2
    # Do NOT exit 2 here — browser scripts can still run without the token.
fi

# Activate venv if present
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.venv/bin/activate"
    echo "[run_all] Activated .venv"
fi

cd "$REPO_ROOT"

FAILURES=()
SKIPPED=()

run_script() {
    local label="$1"
    local cmd="${*:2}"
    echo ""
    echo "============================================================"
    echo "[run_all] >>> $label"
    echo "============================================================"
    if eval "$cmd"; then
        echo "[run_all] <<< $label — EXIT 0 (OK)"
    else
        local rc=$?
        echo "[run_all] <<< $label — EXIT $rc (RECORDED — check SPIKE.md)"
        FAILURES+=("$label (exit $rc)")
    fi
}

# ── Plan 01-01: Browser spike ────────────────────────────────────────
if [ "$PLAN_FILTER" = "all" ] || [ "$PLAN_FILTER" = "01-01" ]; then
    run_script "01_verify_cloak_tag.sh" bash scripts/spike/01_verify_cloak_tag.sh
    run_script "02_cloak_smoke.py" python scripts/spike/02_cloak_smoke.py tests/fixtures/serp/
    run_script "03_pws_consent_probe.py" python scripts/spike/03_pws_consent_probe.py
    run_script "04_death_modes.sh" bash scripts/spike/04_death_modes.sh
fi

# ── Plan 01-02: LLM spike ────────────────────────────────────────────
if [ "$PLAN_FILTER" = "all" ] || [ "$PLAN_FILTER" = "01-02" ]; then
    run_script "05_router_probe.py" python scripts/spike/05_router_probe.py
    run_script "09_label_cards.py (validate)" python scripts/spike/09_label_cards.py --validate tests/fixtures/llm/labelled.jsonl
fi

# ── Plan 01-03: Visit spike ──────────────────────────────────────────
if [ "$PLAN_FILTER" = "all" ] || [ "$PLAN_FILTER" = "01-03" ]; then
    run_script "06_capture_catalog.py" python scripts/spike/06_capture_catalog.py
    run_script "07_extract_fixture.py (all catalog)" bash -c 'for f in tests/fixtures/catalog/*/*.html; do echo "--- $f"; python scripts/spike/07_extract_fixture.py "$f"; done'
    run_script "08_falabella_403_rate.py" python scripts/spike/08_falabella_403_rate.py
fi

# ── Summary ──────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "[run_all] DONE — check SPIKE.md for empirical results"
if [ ${#FAILURES[@]} -gt 0 ]; then
    echo "[run_all] Scripts with non-zero exit (record in SPIKE.md):"
    for f in "${FAILURES[@]}"; do
        echo "  - $f"
    done
    echo "[run_all] NOTE: non-zero exit is expected for empirical failures."
    echo "          Only exit code 2 (missing env) is a setup error, not an empirical result."
else
    echo "[run_all] All scripts exited 0."
fi
