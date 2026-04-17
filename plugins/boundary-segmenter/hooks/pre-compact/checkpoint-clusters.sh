#!/usr/bin/env bash
# boundary-segmenter PreCompact — persist clustering state before context wipe.
#
# The PostToolUse hook already writes state on every event, so this is a
# durability belt-and-suspenders: we rewrite the file via fsync to make sure
# any unflushed buffers hit disk before Claude Code compacts.

set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$(dirname "$0")")")}"
STATE_FILE="$PLUGIN_ROOT/state/boundary-clusters.json"

[[ -f "$STATE_FILE" ]] || exit 0

# Open-and-fsync idiom. Portable across bash on Linux/macOS/Git-Bash.
if command -v python3 >/dev/null 2>&1 && python3 -c "import os" 2>/dev/null; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    exit 0
fi

"$PY" - <<EOF
import os
try:
    with open(r"$STATE_FILE", "r+b") as f:
        os.fsync(f.fileno())
except Exception:
    pass
EOF

exit 0
