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
