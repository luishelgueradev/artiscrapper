#!/usr/bin/env bash
# 04_death_modes.sh — Death-mode provocation for Cloak/Chromium Browser.is_connected() coverage.
#
# Probes 4 death modes: SIGKILL, SIGSTOP, network-drop, OOM.
# Records whether Browser.is_connected() flips to false for each mode.
# This is the highest-risk SPIKE.md §Browser row (01-RESEARCH.md §Assumptions A7).
#
# Source: 01-RESEARCH.md §Pattern 2 (lines 330-356)
#         01-RESEARCH.md §Code Examples → is_connected() check (lines 850-858)
#
# Exit codes:
#   0 — all death-mode tests ran to completion (even if is_connected didn't flip — that's the data)
#   1 — script infrastructure failure (setup error, not empirical failure)
#   2 — missing env / prerequisites
#
# NOTE: Uses set -uo pipefail NOT -e — death modes intentionally crash things.
# The crash IS the test; we must continue after each mode.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACT_DIR="$REPO_ROOT/artifacts/spike"
PID_FILE="$ARTIFACT_DIR/chromium.pid"
OUTPUT_FILE="$ARTIFACT_DIR/death_modes.txt"
mkdir -p "$ARTIFACT_DIR"

echo "[04_death_modes] Starting death-mode provocation..."
echo "[04_death_modes] Artifacts dir: $ARTIFACT_DIR"

# ── Helper: launch a Cloak browser and write chromium child pid ──────────────
LAUNCHER_SCRIPT="$ARTIFACT_DIR/dm_launcher.py"
cat > "$LAUNCHER_SCRIPT" << 'PYEOF'
#!/usr/bin/env python3
"""Death-mode launcher: boots Cloak browser, writes chromium pid, polls is_connected()."""
import asyncio, os, sys, time
from pathlib import Path

import cloakbrowser

PID_FILE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/chromium.pid")
POLL_SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0

async def main():
    browser = await cloakbrowser.launch_async(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    print(f"BROWSER_LAUNCHED pid_placeholder — is_connected: {browser.is_connected()}", flush=True)

    # Find chromium child pid (child of this python process)
    import subprocess
    my_pid = os.getpid()
    try:
        result = subprocess.run(
            ["ps", "--ppid", str(my_pid), "-o", "pid,comm", "--no-headers"],
            capture_output=True, text=True
        )
        lines = result.stdout.strip().splitlines()
        chromium_pid = None
        for line in lines:
            parts = line.strip().split()
            if parts and ('chrome' in parts[-1] or 'chromium' in parts[-1]):
                chromium_pid = int(parts[0])
                break
        # If not found directly, try grandchildren
        if chromium_pid is None:
            # Look 2 levels deep
            result2 = subprocess.run(
                ["pgrep", "-P", str(my_pid)],
                capture_output=True, text=True
            )
            child_pids = result2.stdout.strip().splitlines()
            for cpid in child_pids:
                r3 = subprocess.run(
                    ["ps", "--ppid", cpid.strip(), "-o", "pid,comm", "--no-headers"],
                    capture_output=True, text=True
                )
                for line in r3.stdout.strip().splitlines():
                    parts = line.strip().split()
                    if parts and ('chrome' in parts[-1] or 'chromium' in parts[-1]):
                        chromium_pid = int(parts[0])
                        break
                if chromium_pid:
                    break
    except Exception as e:
        print(f"ERROR finding chromium pid: {e}", file=sys.stderr)
        chromium_pid = None

    if chromium_pid:
        PID_FILE.write_text(str(chromium_pid))
        print(f"CHROMIUM_PID={chromium_pid}", flush=True)
    else:
        print(f"CHROMIUM_PID=UNKNOWN", flush=True)

    # Poll is_connected() for POLL_SECS seconds, reporting on changes
    t_start = time.perf_counter()
    last_state = True
    flip_time = None
    while time.perf_counter() - t_start < POLL_SECS:
        connected = browser.is_connected()
        if connected != last_state:
            flip_time = time.perf_counter() - t_start
            print(f"IS_CONNECTED_FLIPPED: {last_state} -> {connected} at t={flip_time:.1f}s", flush=True)
            last_state = connected
        await asyncio.sleep(0.5)

    if flip_time is not None:
        print(f"FLIP_LAG_SECONDS={flip_time:.1f}", flush=True)
    else:
        print(f"FLIP_LAG_SECONDS=NEVER_FLIPPED", flush=True)
    print(f"FINAL_IS_CONNECTED={browser.is_connected()}", flush=True)

asyncio.run(main())
PYEOF

# Activate venv
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
    source "$REPO_ROOT/.venv/bin/activate"
fi
export LD_LIBRARY_PATH="${HOME}/local-libs/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"

# Initialize output table
cat > "$OUTPUT_FILE" << 'EOF'
| mode             | flipped | lag_seconds | notes |
|------------------|---------|-------------|-------|
EOF

append_row() {
    local mode="$1" flipped="$2" lag="$3" notes="$4"
    printf "| %-16s | %-7s | %-11s | %s |\n" "$mode" "$flipped" "$lag" "$notes" >> "$OUTPUT_FILE"
}

# ── Cleanup function (always run at exit) ────────────────────────────────────
cleanup() {
    echo "[04_death_modes] Cleanup: killing any remaining Cloak/Chromium processes..."
    kill -9 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null || true
    pkill -9 -f cloakbrowser 2>/dev/null || true
    pkill -9 -f "chromium.*spike\|chrome.*no-sandbox.*chromium" 2>/dev/null || true
    pkill -9 -f "dm_launcher.py" 2>/dev/null || true
    rm -f "$PID_FILE" 2>/dev/null || true
    echo "[04_death_modes] Cleanup done."
}
trap cleanup EXIT

# ── Death mode 1: SIGKILL ────────────────────────────────────────────────────
echo ""
echo "[04_death_modes] === Death mode 1: SIGKILL ==="
rm -f "$PID_FILE"

# Launch browser + start polling (background Python process)
python "$LAUNCHER_SCRIPT" "$PID_FILE" 35 > "$ARTIFACT_DIR/dm_sigkill.log" 2>&1 &
LAUNCHER_PID=$!
echo "[04_death_modes] Launcher PID: $LAUNCHER_PID"

# Wait for chromium pid to be written
WAIT=0
while [ ! -f "$PID_FILE" ] && [ $WAIT -lt 15 ]; do
    sleep 1
    WAIT=$((WAIT + 1))
done

if [ ! -f "$PID_FILE" ]; then
    echo "[04_death_modes] WARNING: Could not get chromium pid for SIGKILL test"
    append_row "SIGKILL" "UNKNOWN" "n/a" "chromium pid not found"
else
    CHROMIUM_PID=$(cat "$PID_FILE")
    echo "[04_death_modes] Sending SIGKILL to chromium pid $CHROMIUM_PID"
    kill -KILL "$CHROMIUM_PID" 2>/dev/null || true

    # Wait for launcher to report flip or timeout
    wait "$LAUNCHER_PID" 2>/dev/null || true

    FLIP_LAG=$(grep 'FLIP_LAG_SECONDS=' "$ARTIFACT_DIR/dm_sigkill.log" | tail -1 | cut -d= -f2)
    FINAL_STATE=$(grep 'FINAL_IS_CONNECTED=' "$ARTIFACT_DIR/dm_sigkill.log" | tail -1 | cut -d= -f2)
    FLIPPED=$(grep 'IS_CONNECTED_FLIPPED' "$ARTIFACT_DIR/dm_sigkill.log" | head -1)

    echo "[04_death_modes] SIGKILL flip_lag=$FLIP_LAG final_connected=$FINAL_STATE"

    if [ "$FLIP_LAG" = "NEVER_FLIPPED" ]; then
        append_row "SIGKILL" "NO" "NEVER" "CRITICAL: SIGKILL did not flip is_connected — Phase 2 recycle loop broken"
    else
        append_row "SIGKILL" "YES" "${FLIP_LAG}s" "is_connected() flipped after SIGKILL"
    fi
fi

# ── Death mode 2: SIGSTOP ────────────────────────────────────────────────────
echo ""
echo "[04_death_modes] === Death mode 2: SIGSTOP ==="
rm -f "$PID_FILE"

python "$LAUNCHER_SCRIPT" "$PID_FILE" 35 > "$ARTIFACT_DIR/dm_sigstop.log" 2>&1 &
LAUNCHER_PID=$!

WAIT=0
while [ ! -f "$PID_FILE" ] && [ $WAIT -lt 15 ]; do
    sleep 1
    WAIT=$((WAIT + 1))
done

if [ ! -f "$PID_FILE" ]; then
    echo "[04_death_modes] WARNING: Could not get chromium pid for SIGSTOP test"
    append_row "SIGSTOP" "UNKNOWN" "n/a" "chromium pid not found"
else
    CHROMIUM_PID=$(cat "$PID_FILE")
    echo "[04_death_modes] Sending SIGSTOP to chromium pid $CHROMIUM_PID"
    kill -STOP "$CHROMIUM_PID" 2>/dev/null || true

    # Wait 30s for any flip
    sleep 30

    # Resume chromium
    echo "[04_death_modes] Sending SIGCONT to resume $CHROMIUM_PID"
    kill -CONT "$CHROMIUM_PID" 2>/dev/null || true

    # Let launcher finish
    wait "$LAUNCHER_PID" 2>/dev/null || true

    FLIP_LAG=$(grep 'FLIP_LAG_SECONDS=' "$ARTIFACT_DIR/dm_sigstop.log" | tail -1 | cut -d= -f2)
    FINAL_STATE=$(grep 'FINAL_IS_CONNECTED=' "$ARTIFACT_DIR/dm_sigstop.log" | tail -1 | cut -d= -f2)

    echo "[04_death_modes] SIGSTOP flip_lag=$FLIP_LAG final_connected=$FINAL_STATE"

    if [ "$FLIP_LAG" = "NEVER_FLIPPED" ]; then
        append_row "SIGSTOP" "NO" "NEVER" "Phase 2 needs secondary heartbeat (page.evaluate) — SIGSTOP doesn't flip"
    else
        append_row "SIGSTOP" "YES" "${FLIP_LAG}s" "is_connected() flipped after SIGSTOP"
    fi
fi

# ── Death mode 3: Network drop (Docker-only) ──────────────────────────────────
echo ""
echo "[04_death_modes] === Death mode 3: Network drop ==="
# Check if running inside Docker
if [ -f "/.dockerenv" ]; then
    append_row "network_drop" "UNKNOWN" "n/a" "in Docker but iptables not tested in this run"
else
    append_row "network_drop" "n/a" "n/a" "not_in_docker — skipped per 01-RESEARCH.md line 356"
fi
echo "[04_death_modes] Network drop: $(tail -1 "$OUTPUT_FILE")"

# ── Death mode 4: OOM (Docker-only) ─────────────────────────────────────────
echo ""
echo "[04_death_modes] === Death mode 4: OOM ==="
if [ -f "/.dockerenv" ]; then
    append_row "OOM" "UNKNOWN" "n/a" "in Docker but docker update --memory not tested"
else
    append_row "OOM" "n/a" "n/a" "not_in_docker — skipped per 01-RESEARCH.md line 355"
fi
echo "[04_death_modes] OOM: $(tail -1 "$OUTPUT_FILE")"

echo ""
echo "[04_death_modes] Death mode table:"
cat "$OUTPUT_FILE"
echo "[04_death_modes] Done — artifacts in $ARTIFACT_DIR"
exit 0
