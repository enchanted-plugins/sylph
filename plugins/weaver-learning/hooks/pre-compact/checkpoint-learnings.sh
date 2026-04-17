#!/usr/bin/env bash
# weaver-learning PreCompact — fsync the learnings state so the EMA survives
# context compaction.
#
# The record-* hooks write atomically via tempfile+rename already; this is
# a durability belt-and-suspenders before Claude Code wipes context.

set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$(dirname "$0")")")}"
STATE_FILE="$PLUGIN_ROOT/state/learnings.json"

[[ -f "$STATE_FILE" ]] || exit 0

PY=""
if command -v python3 >/dev/null 2>&1 && python3 -c "import sys" 2>/dev/null; then
    PY="python3"
elif command -v python >/dev/null 2>&1; then
    PY="python"
fi
[[ -z "$PY" ]] && exit 0

"$PY" - <<EOF
import os
try:
    with open(r"$STATE_FILE", "r+b") as f:
        os.fsync(f.fileno())
except Exception:
    pass
EOF

exit 0
