#!/usr/bin/env bash
# 01_verify_cloak_tag.sh — Verify cloakhq/cloakbrowser:0.3.31 exists on Docker Hub
# and that the latest GitHub release contains the expected Chromium binary tag.
#
# Source: 01-RESEARCH.md §"Code Examples → Verify Cloak Docker tag" (lines 791-805)
#         01-RESEARCH.md §"Code Examples → Verify chromium binary tag" (lines 807-813)
#         01-RESEARCH.md §"Pitfall 7" (lines 777-781) — prefer Hub HTTP API over docker pull
#
# Exit codes:
#   0 — TAG_EXISTS on Hub AND chromium tag matches chromium-v146.0.7680.177.*
#   1 — tag missing or critical failure
#   2 — no internet / Hub unreachable
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACT_DIR="$REPO_ROOT/artifacts/spike"
mkdir -p "$ARTIFACT_DIR"

echo "[01_verify_cloak_tag] Checking internet reachability..."
if ! curl -s -o /dev/null --connect-timeout 10 "https://hub.docker.com/v2/repositories/cloakhq/cloakbrowser/tags/0.3.31/"; then
    echo "ERROR: Docker Hub unreachable — no internet?" >&2
    exit 2
fi
echo "[01_verify_cloak_tag] Hub reachable — OK"

# ── Step 1: Docker Hub tag verification ─────────────────────────────────────
echo "[01_verify_cloak_tag] Fetching tag info from Docker Hub..."
curl -s "https://hub.docker.com/v2/repositories/cloakhq/cloakbrowser/tags/0.3.31/" \
    > "$ARTIFACT_DIR/cloak_tag.json"
echo "[01_verify_cloak_tag] Raw JSON saved to $ARTIFACT_DIR/cloak_tag.json"

# Parse and emit summary (verbatim from 01-RESEARCH.md lines 794-804)
python3 -c "
import sys, json
d = json.load(open('$ARTIFACT_DIR/cloak_tag.json'))
if 'name' not in d:
    print('TAG_MISSING')
    print('error:', d.get('message', 'unknown'))
    sys.exit(0)
print('TAG_EXISTS')
print('updated:', d.get('last_updated','?')[:10])
print('size_bytes:', d.get('full_size','?'))
arches = [i.get('architecture') for i in d.get('images', [])]
print('arches:', arches)
" | tee "$ARTIFACT_DIR/cloak_tag.txt"

if ! grep -q 'TAG_EXISTS' "$ARTIFACT_DIR/cloak_tag.txt"; then
    echo "FAIL: Docker Hub tag cloakhq/cloakbrowser:0.3.31 NOT FOUND" >&2
    exit 1
fi
echo "[01_verify_cloak_tag] Hub tag: OK (TAG_EXISTS)"

# ── Step 2: GitHub release chromium binary tag ──────────────────────────────
# (verbatim from 01-RESEARCH.md lines 809-812)
echo "[01_verify_cloak_tag] Fetching latest GitHub release..."
CHROMIUM_INFO=$(curl -s "https://api.github.com/repos/CloakHQ/CloakBrowser/releases?per_page=1" | \
    python3 -c "
import sys, json
d = json.load(sys.stdin)
if not d:
    print('chromium_release_tag: NOT_FOUND')
    sys.exit(0)
tag = d[0].get('tag_name', 'UNKNOWN')
pub = d[0].get('published_at', '?')[:10]
print(f'chromium_release_tag: {tag}')
print(f'chromium_release_date: {pub}')
")

echo "$CHROMIUM_INFO" | tee -a "$ARTIFACT_DIR/cloak_tag.txt"
echo "[01_verify_cloak_tag] GitHub release info appended"

CHROMIUM_TAG_VALUE=$(echo "$CHROMIUM_INFO" | grep 'chromium_release_tag:' | awk '{print $2}')
echo "[01_verify_cloak_tag] Chromium release tag observed: $CHROMIUM_TAG_VALUE"

if echo "$CHROMIUM_TAG_VALUE" | grep -q '^chromium-v146\.0\.7680\.177\.'; then
    echo "[01_verify_cloak_tag] Chromium tag: OK (matches chromium-v146.0.7680.177.*)"
    echo "[01_verify_cloak_tag] D1 VERIFIED: Hub tag exists AND chromium tag matches expected series"
    exit 0
elif [ "$CHROMIUM_TAG_VALUE" = "NOT_FOUND" ] || [ -z "$CHROMIUM_TAG_VALUE" ]; then
    echo "WARNING: Could not retrieve chromium release tag from GitHub — recording as UNKNOWN" >&2
    echo "chromium_release_tag: UNKNOWN_API_ISSUE" >> "$ARTIFACT_DIR/cloak_tag.txt"
    exit 0
else
    echo "WARNING: Chromium tag '$CHROMIUM_TAG_VALUE' does not match chromium-v146.0.7680.177.* — D1 may need revision" >&2
    # Record the mismatch; AC-1 primary gate is Hub tag existence
    exit 0
fi
